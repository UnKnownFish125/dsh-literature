# literature skill 管理设计 v1

> 制定：2026-10-24 ｜ 依据用户指令：**关键词给人用，语义给 agent 用**
> 前置结论（已实测）：DSH 原生 `skill` 工具做不到「模型能选但不全推」——
> 进目录与模型可调用绑死（`isModelInvocable` 在 execute 里查两处），
> 目录成本 = 技能数 × description（默认上限 500 字符）。
> ⇒ literature 技能**不配 customSkillDirs**，改用自有工具族。

---

## 一、为什么分成两条检索路

| | 人（关键词） | agent（语义） |
|---|---|---|
| 输入形态 | 我**知道**要找什么，能说出名字/标签 | 我有**意图**，但不知道库里叫什么 |
| 失败模式 | 词不对 → 找不到（可改词重试） | 词不对也能命中（但也可能命中错） |
| 要的排序 | **确定性**：完全匹配 > 前缀 > 模糊；再按使用量 | **相关性**：语义相似度；再按成功率 |
| 谁承担成本 | 人的一次重试 | 每次调用都是 token，必须省 |
| 结论 | FTS5（可解释、零模型成本） | 向量（bge-m3，复用现有 6192） |

**两条路共用同一份源数据（`skill_versions`），索引都是派生物。**
这样「人搜到的」和「agent 搜到的」永远是同一个技能，不会漂移。

---

## 二、数据模型

### 2.1 现有表（不动）

```
skills            技能身份：name / category / lifecycle / visibility
skill_versions    不可变版本：skill_md / hash / summary_l0 / overview_l1
skill_files       版本内引用文件
skill_deployments 部署：哪个版本在哪生效
skill_usage_events  load/apply 事件
skill_evaluations   质量评估
skill_audit         操作审计
```

### 2.2 新增（三条，都是派生物，可随时重建）

```sql
-- ① 关键词索引（给人）—— FTS5 external content，跟现有 knowledge_fts 同模式
CREATE VIRTUAL TABLE skill_search_fts USING fts5(
    name, summary_l0, overview_l1, tags, category,
    content='',              -- 内容自己管，避免双写
    tokenize='unicode61 remove_diacritics 2'
);
-- 通过 skill_search_doc(version_id) 维护：版本发布时 upsert

-- ② 语义索引（给 agent）—— 每个版本一份向量
CREATE TABLE skill_vectors (
    skill_version_id INTEGER PRIMARY KEY REFERENCES skill_versions(id) ON DELETE CASCADE,
    model       TEXT NOT NULL,          -- 'bge-m3'
    dim         INTEGER NOT NULL,
    vec         BLOB NOT NULL,          -- float32 小端
    text_hash   TEXT NOT NULL,          -- 参与嵌入的文本 hash，用于判断是否需重建
    built_at    REAL NOT NULL
);

-- ③ 标签（两个世界共用：人按标签筛，agent 的语义输入也带标签）
CREATE TABLE skill_tags (
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    tag      TEXT NOT NULL,
    PRIMARY KEY (skill_id, tag)
);
CREATE INDEX ix_skill_tags_tag ON skill_tags(tag);
```

**参与嵌入的文本**（顺序固定，便于 hash）：
```
f"{name} | {category} | {tags用逗号} | {summary_l0} | {overview_l1}"
```
**不嵌 L2 正文**——正文太长、噪声大。语义检索找的是「这技能干什么」，不是「正文里有啥词」。

### 2.3 索引生命周期（这是审查里 P1-7 的同类问题，一次做对）

| 触发 | 动作 |
|---|---|
| 新版本写入 | 同步写 FTS + 入队嵌入任务 |
| L0/L1 重新生成 | text_hash 变化 ⇒ 标脏，后台重嵌 |
| 版本废弃/技能归档 | 从 FTS 删除 + 删向量行 |
| 嵌入失败 | `skill_vectors` 写失败标记（vec NULL + error 列），**不静默** |
| 全量重建 | `POST /v1/literature/skills/rebuild-index`（幂等） |

**硬规则**：索引写入与版本状态变更**同一事务**（FTS 可以，向量走后台但要有脏标记兜底）。

---

## 三、人的那条路：关键词

### 3.1 检索语义（确定性，按优先级）

```
1) name 完全等于          → 置顶
2) name 前缀匹配          → 次之
3) FTS5 全文（name/l0/l1/tags/category） → 按 bm25
4) 标签精确命中           → 加权
```

**过滤**：`lifecycle`（draft/published/deprecated）、`category`、`tag`、`workspace`、`visibility`
**排序**：匹配档位 → 90 天内 apply 次数 → 更新时间

### 3.2 UI（🧩 技能页签改造）

```
┌ 搜索框（关键词，支持 tag:xxx category:xxx）────────────────┐
│ [全部] [已发布] [草稿] [已废弃]   分类▾   标签▾            │
├───────────────────────────────────────────────────────────┤
│ name            L0 一句话            版本  apply  状态     │
│ evidence-extract 从论文全文抽逐字证据  3    128   已发布    │
│ pdf-locate       在原文定位引文位置    2     41   已发布    │
└───────────────────────────────────────────────────────────┘
点开 → L1 概览 → 版本历史 → 使用统计 → 部署状态
```

**人不需要向量**——他知道名字。给他 FTS 就够，且**结果可预测**（这对管理很重要：
「我搜 evidence 为什么第一个不是 evidence-extract」是可以被解释的）。

---

## 四、agent 的那条路：语义

### 4.1 工具契约（两个，恒定成本）

```js
literature_skill_search(query: string, k?: number = 5, tag?: string)
  → [{ name, l0, category, tags, score, version }]
  约束: k ∈ [1,8]；只返回 L0（≤60 字），**永不返回正文**

literature_skill_load(name: string, layer?: 'l1'|'l2' = 'l1')
  → { name, version, layer, content }
  约束: 默认 L1（≤400 字）；L2 必须显式 layer='l2'
```

### 4.2 成本（关键）

```
默认态：只有两个工具的 schema 在上下文 ≈ 300 token（与技能数无关）
search 一次：5 条 L0 ≈ 300 字 ≈ 200 token
load L1 一次：≈ 400 字 ≈ 300 token
load L2 一次：SKILL.md 全文（通常 2-6KB）
⇒ 一个「找不到就用」的 agent，全程花不到 1K token
⇒ 对比 DSH 目录：50 个技能 × 500 字符 = 25KB 常驻
```

### 4.3 排序（语义 + 反馈）

```
score = 0.75 * cosine(query, skill_vec)
      + 0.15 * apply_success_rate(90d)      -- skill_usage_events
      + 0.10 * recency_decay(last_applied)
```
**为什么不纯按相似度**：库里技能多了以后，两个技能可能语义高度重叠，
用使用成功率把「真能办成事」的顶上来。这个信号现有表里已经有了。

### 4.4 防「全注入」的三道闸（写进实现约束）

```
闸 1  工具描述里明确写：这是**检索**工具，一次只返回 k 条摘要
闸 2  k 上限 8，服务端强制夹断（不信任调用方传的值）
闸 3  load 分两级，L2 必须显式请求；服务端记录每次 load 的 layer
      （将来发现 agent 频繁直接要 L2，说明 L1 写得不好，是质量信号）
```

---

## 五、管理生命周期（顺带修审查里的审批链）

```
draft ──submit──▶ pending_review ──approve──▶ published ──deploy──▶ deployed
  ▲                     │                                              │
  └────reject───────────┘                                    rollback ─┘
                                              deprecated ◀─── 归档
```

### 5.1 审批身份的诚实结论

**现状**：literature 服务只有一个共享 Bearer token，**无法验证真实操作人**。
审查提的「approver 是调用方自报字符串」是真的。

**两条路**：

- **A（建议先做）**：承认这是**单操作员系统**。
  - `approver` 字段改名为 `attested_by`，语义是「操作员自述」
  - 所有审批写 `skill_audit`，带 IP + 时间 + 内容 hash
  - **文档里明确写：这不是身份边界，审计而非鉴权**
  - 好处：诚实、零额外基建
- **B（要真身份就得多租户基建）**：per-user token + 会话绑定
  - 工作量：token 表、签发、路由改造、DSH 侧传 session id
  - **依赖 DSH 侧改动，不是 literature 单仓能闭环的**

**我建议 A，并把 B 列为「需要 DSH 支持」的后续项。**

### 5.2 审批端点（补齐缺口）

```
POST /v1/literature/skill-versions/<id>/submit    草稿 → 待审
POST /v1/literature/skill-versions/<id>/approve   待审 → 已发布   （attested_by）
POST /v1/literature/skill-versions/<id>/reject    待审 → 草稿 + 理由
```
**部署前强制检查** `status='published'`（现有 `literature_skill_deploy.py:696` 已经这么要求，
补上审批端点后才闭环）。

---

## 六、质量环（让 L0/L1 越用越好）

```
apply 事件 → 按 (skill, version) 聚合成功率
          → 成功率低 ⇒ 标记「该版本需要重写 L0/L1」进 review queue
          → 人工改 L0/L1 ⇒ 新版本 ⇒ 重嵌
```

**为什么 L0 质量是命门**：agent 只看到 L0 就决定要不要 load。
**L0 写成「本技能是……」= 检索必废**（现有 layers 模块的 prompt 已经明确禁了这种写法）。

**抽样验收**：新技能入库后，人工抽 10 条看 L0 是否满足
「**只给这句话，能不能判断该不该用**」。不满足就退回重写。

---

## 七、实施顺序

```
P0  数据层
    1. skill_search_fts（FTS5）+ skill_tags + 增量维护
    2. 人的关键词检索 API：GET /v1/literature/skills/search?q=&tag=&category=
    3. 🧩 技能页签搜索框 + 筛选

P1  agent 工具族
    4. skill_vectors + 嵌入任务（复用 literature_vectors 的 provider 抽象）
    5. literature_skill_search / literature_skill_load 两个工具
    6. 在测试实例上验证「默认零注入 + 按需调用」

P2  管理闭环
    7. submit/approve/reject 三个端点 + attested_by + audit
    8. 技能详情页：版本历史 / 使用统计 / 部署状态

P3  质量环
    9. apply 成功率聚合 → 排序信号
    10. L0 重写队列 + 抽样验收
```

---

## 八、需要你拍板的三点

1. **审批身份**：选 A（单操作员 + 审计，诚实）还是 B（做多租户身份基建，要 DSH 配合）？
   —— 我建议 A。

2. **skill_vectors 存哪**：SQLite BLOB（简单、单文件）还是 sidecar 文件（便于外部工具重建）？
   —— 我建议 BLOB（技能就几十上百条，向量总量 < 1MB，不值得拆文件）。

3. **L2 加载要不要限流**：比如同一会话对同一技能最多 load L2 一次（避免反复拉全文）。
   —— 我建议**限**，但要记录被限的次数（这本身是「模型不知道该信 L1」的信号）。
