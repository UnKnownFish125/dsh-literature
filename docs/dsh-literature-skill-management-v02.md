# dsh-literature Skill 管理体系设计方案 v0.2

日期：2026-09-09　状态：**待实施（首周范围已收紧）**
v0.1 方案：`docs/dsh-literature-skill-management-v01.md`
依据：astra 独立评审 `docs/skill-management-review-astra-final-20260909.md`（含运行级 probe 实测）+ 主 agent 实测交叉验证

---

## 一、结论与范围

**能做，但不能照 v0.1 原样实施。** 首周只交付：

> 受管 skill 登记 / 不可变版本 / 人工审核 / 单机安全发布与回滚 / 真实加载计数 / 人工效果反馈

**首周明确不做**：自动成熟蒸馏、每次 LLM 评分、低分自动归档、多实例发布、bundle 多文件可靠发布。

**核心认知（评审结论）**：最大障碍不是建表，而是**"受管版本 → DSH 实际加载版本 → 任务效果"缺少可靠关联**。
`skill` 是**正文加载器，不是技能执行器**——加载成功无法证明任务成功。literature 只能是**已收管** skill 的权威源；未登记的 GitHub 素体在管理边界之外。

## 二、架构原则（实测/源码支撑）

| # | 原则 | 依据 |
|---|---|---|
| 1 | **skill 独立表**，不复用 `knowledge_items` | `create_knowledge_item` 自动写共享 FAISS（`literature_domain.py:741-763`）；library 白名单双拒（`:693-694` + `:148-159`） |
| 2 | **部署目标来自可信配置**，不硬编码 | `agentsHome` 由 config→`DSH_AGENTS_HOME`→`homedir/.agents`（filesystem `:78`） |
| 3 | **默认工作区私有**，显式审核才发布 global | 复盘 `:125-131`（workspace 必须真实 UUID + 写入显式归属） |
| 4 | **退役 = 物理移出发现根** | `lifecycle:archived` + chmod 444 仍被 list（filesystem `:581-613` 无过滤，实测） |
| 5 | **staging 置于发现根之外** | `root/.staging/SKILL.md` 会被扫到 |
| 6 | **正文按需，摘要目录有成本** | catalog 以 user 消息注入（tool-skill `:203-260`）——不承诺零上下文/永不失效缓存 |
| 7 | **两条调用路径都要观测** | 工具 `:138-156` 与用户 `/slug` `:168-200`（后者绕过工具） |
| 8 | **版本不可原地改** | 内容不可变，`UNIQUE(skill_id,version)` |
| 9 | **显式迁移**，不依赖 `install_schema` | 实测：DROP COLUMN 后重跑不恢复；server 无 ALTER/schema_migrations |

## 三、数据模型（5 张业务表 + 复用分类 + 迁移表）

统一：均含 `created_at`；可变表另有 `updated_at`；启用 FK；内容版本不可原地修改。

### 1. `skills`（管理态元数据）
`id`(UUID PK) / `slug` / `title` / `category_id`(FK) / `scope`(global|workspace) / `workspace_id`(nullable) / `origin_workspace_id` / `lifecycle`(draft|active|deprecated|archived) / `active_version_id`(FK) / `row_version`(乐观锁) / `created_by` / `created_at` / `updated_at` / `deleted_at`

**约束**：
- `scope=global` → `workspace_id IS NULL`；`scope=workspace` → **真实 UUID 且非空**
- **partial unique**：global slug 唯一、`(workspace_id,slug)` 唯一——**不得用可 NULL 复合 UNIQUE 假装全局唯一**
- 拒绝把"漏传工作区"解释为全局发布

### 2. `skill_versions`（不可变快照）
`id` / `skill_id`(FK) / `version` / `parent_version_id` / `skill_md`(含完整 frontmatter 原文) / `content_sha256` / `artifact_sha256` / `artifact_uri` / `manifest_json`(资源路径/大小/hash) / `source_kind` / `source_url` / `source_ref`(固定 commit) / `source_key`(幂等) / `distilled_from_json`(memory_id+workspace_id+source revision/hash) / `dependencies_json` / `compatibility_json` / `permission_requests_json` / `created_by` / `created_at`

**约束**：`UNIQUE(skill_id,version)`；MVP 单文件也保留 manifest 结构；**不支持资源 bundle 时明确拒绝部署，不静默丢脚本**。

### 3. `skill_deployments`（部署状态机）
`id` / `skill_id` / `target_id`(可信配置解析出的实例/根) / `target_scope` / `workspace_id` / `deployed_path` / `desired_version_id` / `applied_version_id` / `expected_current_hash` / `observed_hash` / `generation` / `state`(pending|applying|verified|failed|drift|removed) / `attempt_count` / `next_retry_at` / `last_error` / `last_verified_at` / `operation_key`(UNIQUE) / `created_at` / `updated_at`

**约束**：`desired` 与 `applied` **分离**；发布失败保留目标数据与旧运行版；**不得只写 `deployed=true`**。

### 4. `skill_usage_events`（加载/应用事件）
`id` / `producer_id` / `event_key`(UNIQUE with producer) / `skill_id` / `skill_version_id`(无法确认时 NULL) / `deployment_id` / `observed_content_hash` / `invocation_kind`(tool|slash) / `event_kind`(load|apply) / `session_id` / `turn_id` / `tool_call_id` / `run_id` / `workspace_id` / `occurred_at`

**约束**：计数**从去重事件派生**，不直接 `use_count++`；版本无法确认时**保留 unknown**，不按 slug 计到最新版。

### 5. `skill_evaluations`（评价）
`id` / `skill_version_id` / `usage_event_id` / `run_id` / `kind`(user_rating|agent_self|task_outcome|approval) / `reviewer_id` / `model_id` / `rubric_version` / `score`(nullable) / `outcome`(success|failure|unknown|cancelled) / `decision`(approve|reject nullable) / `evidence_ref` / `comment` / `created_at`

**约束**：用户 1-5 与 agent 0-1 **按 kind 校验、分开聚合**；评价**必须绑定版本**；任务 outcome 须**独立证据**，不从 agent 自评分推导。

### 6. `categories`（复用）
现有字段保留；补**全局分类读取（并集）**、父子作用域校验、技能引用校验。**删除分类不得隐式退役技能**。

### 7. `schema_migrations`
`version`(PK) / `applied_at` / `checksum`

### 统计口径（纠正 v0.1）
- `load_count ≠ applied_run_count`
- effectiveness 只用**已评价的 distinct run**：`success/(success+failure)`，同时显示**样本数、版本、观察窗口、评价覆盖率**
- 无评价返回 **NULL**；`unknown`/`cancelled` **不算失败**
- **不跨用户分/agent 分混合平均**

## 四、流程

| 环节 | 规则 |
|---|---|
| **导入（GitHub 素体）** | 固定 commit → `source_key` 幂等 → 进 **draft**；默认私有；静态扫描（路径穿越/符号链接/危险命令）；**首周不自动部署** |
| **蒸馏（deepmemory）** | deepmemory 只做 **draft 生产者**（不写 SKILL.md、不维护第二张权威表）；literature 负责蒸馏落库 |
| **审核** | draft → active 需人工审核；**发布 global 需显式批准** |
| **部署** | 单机单写者；可信 root；全候选同名冲突检测；根外 staging；hash 校验；原子替换；**原生解析 + 目标 cwd 实际 list/get 核验**；失败保留旧版；可回滚 |
| **观测** | 覆盖 tool + `/slug` 两条路径；事件幂等；版本无法确认→unknown |
| **评价** | 用户星级 / agent 自评 / 任务 outcome 三源分列；人工录入为主 |
| **退役** | **物理移出发现根**（+ 可选双禁用 invocation）；已进入会话的正文无法撤回（需在 UI 说明） |
| **记忆归档** | **仅当部署核验通过 + 人工确认**，源记忆才退出召回，且**必须可恢复** |

## 五、实施路径（3 个 PR）

### PR1（D1-D2）：管理数据
固定 scope/slug/计数契约；**显式迁移 + 5 表**；CRUD API；版本创建；原样 SKILL.md 校验（**正文非空**，DSH 侧空正文也接受）；来源幂等；分类隔离测试。
**验收**：冲突拒覆、跨区不泄露、重复导入不翻倍、现有 14 单测绿。

### PR2（D3-D4）：安全发布
单机单写者部署器；可信 root 配置；路径/符号链接校验；全候选同名检测；根外 staging；hash 校验；原子替换；desired/applied 分离；重试与漂移告警；旧版回滚。
**验收**：目标 cwd 实际 list/get 能读到；篡改→drift；中断不留半文件；同名遮蔽告警；回滚成功；**MVP 只承诺单文件**。

### PR3（D5-D7）：最小闭环
管理视图（列表/分类/来源/版本差异/审核/发布状态/人工评价）；加载观测（tool + `/slug`，幂等）；人工 task outcome；`/memory distill` 手动候选 → literature draft。
**验收**：重复事件不翻倍；两种调用路径都计数；只读 archived 仍加载的**负向用例**；上下文目录增长可见；源记忆归档可恢复。

## 六、风险与门禁

| 级别 | 风险 | 门禁 |
|---|---|---|
| **P0** | **信任/隔离失效**——GitHub 指令或含项目细节的记忆进入全局运行目录并传播；**frontmatter 的 permissions 声明不提供执行限制** | 固定 commit、人工审核、敏感信息清理、默认私有、显式全局发布权限、路径/资源校验 |
| **P1** | **库内版本 ≠ 运行版本**——目录解析错误、优先级遮蔽、未受管文件覆盖、半部署、只读假退役 | 独立部署记录、内容 hash、原生加载核验、原子发布、可回滚、真正移出扫描根 |
| **P1** | **错误反馈驱动错误归档**——加载算成功、漏 `/slug`、LLM 自评替代结果、draft 入库即归档 | 版本化事件、独立 outcome 证据、unknown 状态、样本门槛；**首周禁止自动淘汰** |

## 七、数据来源与采集契约

### 7.1 数据从哪来（实测：会话日志事件类型）

DSH 会话日志 `sessions/<cwd>/<sid>/session.jsonl.zstd` 实测事件类型：
`assistant/chunk` / `assistant/message` / `user/message` / `tool/call` / `tool/result` / `tool-call-chunks` / `step/start` / `step/end` / `turn/start` / `session` / `session/title` / `sandbox/mode` / `permission/preset` / `subagent/*` / `agent/inbox/spliced`

**结论：对话与轨迹已覆盖大部分数据需求。**

| 层 | 要收什么 | 来源 | 可得性 |
|---|---|---|---|
| 加载 | 技能加载次数、时间、会话/轮次 | `tool/call`(name=`skill`) + `tool/result` | ✅ |
| 加载（另一路径） | 用户 `/slug` 直接调用 | `user/message` 解析 `/slug` | ✅（需解析） |
| 应用 | 是否真按技能步骤执行 | 轨迹后续 tool 调用序列 vs 技能步骤 | ⚠️ 需推断 |
| 结果 | 任务成功/失败 | `user/message` 反馈（修正/确认/否定） | ⚠️ 信号弱，需显式评价补强 |
| 版本 | 用了哪个版本 | **轨迹无 version/hash** | ❌ 需部署记录 + 时间窗 |

### 7.2 三个缺口与补法

| 缺口 | 补法 |
|---|---|
| 版本关联 | 部署时记录「何时部署哪个版本」（`skill_deployments`）→ 用**时间窗**关联加载事件；无法确定时记 **unknown**，禁止按 slug 关联到最新版 |
| 任务结果 | 用户反馈为主：修正词（"不对/应该是"）→ 负信号；确认词（"可以/就这样"）→ 正信号；外加**显式评价**（人工打星） |
| 应用层 | 先简单规则（技能正文里的命令是否出现在后续 bash 调用中），后续再优化 |

### 7.3 职责划分（避免双写）

```
┌──────────────────────────────────────────────┐
│ 日志注入插件（会话创建时注入，用户侧实现）      │
│  · 监听 tool/call、tool/result、user/message  │
│  · 提取 skill 加载 / /slug 调用 / 用户反馈     │
│  · 携带 session_id、turn_id、时间戳            │
└───────────────────┬──────────────────────────┘
                    │ POST /v1/skill-events（幂等 event_key）
                    ▼
┌──────────────────────────────────────────────┐
│ literature（只做存储 + 分析）                  │
│  · skill_usage_events（去重事件）              │
│  · skill_deployments（版本时间窗）             │
│  · 统计 / 效果评估 / 优化建议                  │
└──────────────────────────────────────────────┘
```

**literature 不直接读会话日志**（避免重复采集与权限问题）。

### 7.4 接口契约

**事件上报** `POST /v1/skill-events`
```json
{
  "producer_id": "log-injector-v1",
  "event_key": "session-4cb6d508:turn3:call_9wjC...",
  "event_kind": "load",
  "invocation_kind": "tool",
  "skill_name": "plot-chart",
  "skill_version_id": null,
  "observed_content_hash": null,
  "session_id": "session-4cb6d508-...",
  "turn_id": "turn-3",
  "tool_call_id": "call_9wjC...",
  "workspace_id": "bf4722bc-...",
  "occurred_at": 1788925050915
}
```

**反馈上报** `POST /v1/skill-evaluations`
```json
{
  "skill_version_id": 12,
  "kind": "task_outcome",
  "outcome": "success",
  "reviewer_id": "user",
  "evidence_ref": "session-4cb6d508:turn-3",
  "comment": "生成的图直接可用",
  "created_at": 1788925100000
}
```

**硬约定**（均来自实测踩坑）：
1. `event_key` 必须幂等——重复上报不翻倍
2. `skill_version_id` 不确定就 `null`——**禁止按 slug 关联最新版**
3. `workspace_id` 按 `#668` 规则解析（`DSH_SESSION_ID` → `workspace.json`）——**禁止兜底假值**
4. 用户 `/slug` 调用**必须上报**（`invocation_kind: "slash"`），否则漏计

## 七之二、已确认决策（2026-09-09 用户拍板）

| # | 决策 | 用户决定 | 执行要点 |
|---|---|---|---|
| 1 | 部署目标根 | **C**：受管目录 + `customSkillDirs` | 目录待定（建议 `/www/dsh/skills-managed`）；用户后续另写"日志注入插件"负责加载 |
| 2 | 首周范围 | 收集提炼 + 部署 + **开始收数据** | 后续按第一周数据引导优化 |
| 3 | 默认 scope | **A**：workspace 私有 | "通用的会转向全局" → 需**分类维度**支持 `私有→候选通用→审核→global` |
| 4 | bundle（多文件） | **支持**（修正原建议） | 用户场景为"带 skill 做事收数据"，多文件技能常见；改用**整包目录原子替换** + manifest |
| 5 | deepmemory 蒸馏 | **手动** | 蒸馏成功标准待定，首周不做自动判定 |

**bundle 支持的具体设计**：
- 存储：`/www/dsh/skill-packages/<slug>/<version>/`（整包）+ 库内 `manifest_json`（文件清单 + 单文件 hash + 整包 hash）
- 部署：写临时目录 → **目录级 rename**（同文件系统内原子）
- 安全：导入时静态扫描路径穿越（`..`）、绝对路径、符号链接、可疑命令；**默认不自动执行包内脚本**
- 拒绝条件：超大小/文件数上限、含符号链接、路径穿越——**不再拒绝多文件本身**

## 八、参考

- v0.1 方案：`docs/dsh-literature-skill-management-v01.md`
- astra 独立评审（最终）：`docs/skill-management-review-astra-final-20260909.md`
- astra 评审（首轮，无工具版）：`docs/skill-management-review-astra-20260909.md`
- 子 agent 工具调用问题：`docs/dsh-subagent-toolcall-issues.md`
- 事故复盘：`docs/dsh-literature-workspace-scope-postmortem.md`
- 记忆：`#691`（子 agent 工具规范）、`#692`（DSH skill + literature 实测事实）
