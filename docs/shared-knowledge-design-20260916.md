# 跨工作区知识供给设计（Q1-D：显式发布/共享表 + 只读投影 + ACL）

> 状态：**设计待评审**，未写代码
> 日期：2026-09-16
> 决策依据：用户裁定「方案 D，授权由对应工作区会话发起」
> 评审依据：astra 独立评审（明确否决 B 直跳过滤、否决 C 写 bias；短期先 A）

---

## 0. 一句话

把"跨工作区可见"从**过滤器的例外**改成**被授予的资产**：发布方工作区**显式发布**一条知识到共享池，共享池是**只读投影**（不复制、不改原件），读取侧按 ACL 决定可见性。

---

## 1. 为什么不能走捷径（astra 裁定 + 实测）

| 方案 | 否决理由 |
|---|---|
| **A 显式传 ws** | 不是跨区供给，只是"把 UUID 告诉别人"。**作为短期过渡可接受**，长期不解决问题 |
| **B shared 跳过过滤** | `search_knowledge:985` 的 `if workspace_id:` 是**唯一**隔离点，跳过它 = **首次让通用检索跨越工作区边界**，且 `search_knowledge` 里**连 bias 例外都没有**（bias 例外只在 `list_knowledge`），因此"照抄 bias"不成立 |
| **C 写进 bias** | bias 是**行为约束库**（`kb_bias_constraints` 用于 system prompt 注入），服务端还有"bias 不可归档"的硬保护；把论文知识塞进去会污染约束语义 |

**实测补充**：上游 deepmemory 对**空 workspace_id** 返回的是**任意工作区**的数据（不是全部、不是空）——所以任何"空即全局"的假设都是错的。

---

## 2. 数据模型

### 2.1 新表 `shared_publications`

```sql
CREATE TABLE shared_publications (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  knowledge_id    INTEGER NOT NULL,          -- 指向 knowledge_items.id（原件，不复制）
  owner_workspace TEXT    NOT NULL,          -- 发布方工作区 UUID（权威归属）
  scope           TEXT    NOT NULL DEFAULT 'workspace'
                  CHECK(scope IN ('workspace','public')),  -- 可见范围
  status          TEXT    NOT NULL DEFAULT 'active'
                  CHECK(status IN ('active','revoked')),
  title           TEXT    NOT NULL DEFAULT '',   -- 投影用（发布时的快照，避免读时耦合）
  summary         TEXT    NOT NULL DEFAULT '',
  concept         TEXT    NOT NULL DEFAULT '',
  library         TEXT    NOT NULL DEFAULT '',
  published_by    TEXT    NOT NULL DEFAULT '',   -- 发起会话标识（谁发布的）
  published_at    REAL    NOT NULL,
  revoked_at      REAL,
  revoke_reason   TEXT    NOT NULL DEFAULT '',
  row_version     INTEGER NOT NULL DEFAULT 1,
  UNIQUE(knowledge_id)                        -- 一条知识至多一条发布记录
);
CREATE INDEX idx_shared_status ON shared_publications(status, scope);
CREATE INDEX idx_shared_owner  ON shared_publications(owner_workspace, status);
```

### 2.2 新表 `shared_grants`（ACL）

```sql
CREATE TABLE shared_grants (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  publication_id  INTEGER NOT NULL,
  grantee_workspace TEXT  NOT NULL,          -- 被授权的工作区 UUID
  permission      TEXT NOT NULL DEFAULT 'read'
                  CHECK(permission IN ('read')),
  granted_by      TEXT NOT NULL DEFAULT '',
  granted_at      REAL NOT NULL,
  revoked_at      REAL,
  UNIQUE(publication_id, grantee_workspace)
);
```

**设计要点**：
- **只读投影**：共享池**不复制正文**，`knowledge_id` 指向原件；读时 join 取当前内容，**发布方更新原件，读者看到的是最新**（这是"投影"而非"快照"的正确语义）。
- **title/summary/concept 冗余快照**：仅用于**列表展示**（避免 N+1 join），**检索结果以原件为准**。
- **权限只有 `read`**：v1 不允许跨区写。要"共同编辑"是另一个议题（会引入冲突解决），不在本期。

---

## 3. 读写路径

### 3.1 发布（写侧，授权由**对应工作区会话发起**）

```
POST /v1/literature/shared/publications
  body: { knowledge_id, scope: 'workspace'|'public', workspace_id: <发布方> , granted_workspaces: [...] }
  规则：
   - 服务端校验 knowledge_id 的 workspace_id == body.workspace_id（否则 403，防代发）
   - workspace_id 必填（沿用本次修复后的"禁兜底"原则）
   - scope='workspace' 时必须给 granted_workspaces（至少一个），否则 400
   - 写 audit：action='shared.publish'
```

**"授权由对应工作区会话发起"的落地**：
- 谁发布 = **该工作区自己的会话**（`published_by` 记录会话标识）
- **其他工作区不能替它发布**（服务端按 `knowledge_items.workspace_id` 校验）
- 撤销同理：只有 `owner_workspace` 能撤销

### 3.2 读取（读侧，投影 + ACL 过滤）

```
search_knowledge(query, k, workspace_id=W, library=None, include_shared=False)
  当 include_shared=True：
    - 本区结果照旧（现有逻辑不动）
    - 追加：JOIN shared_publications sp ON sp.knowledge_id = ki.id
            WHERE sp.status='active'
              AND (sp.scope='public' OR EXISTS(
                    SELECT 1 FROM shared_grants g
                    WHERE g.publication_id=sp.id AND g.grantee_workspace=W
                      AND g.revoked_at IS NULL))
              AND sp.owner_workspace != W            -- 自己的不重复
    标记 source='shared'，附 owner_workspace
```

**关键**：**不改现有 `if workspace_id:` 分支**——共享结果是**另一条 SQL 分支并集**。这样：
- 不破坏现有隔离语义（astra 的核心关切）
- 共享可见性**完全由 sp/g 两张表决定**，可审计、可撤销
- `include_shared` 默认为 **False**（渐进启用）

### 3.3 撤销 / 收回

```
POST /v1/literature/shared/publications/<id>/revoke   { workspace_id, reason }
POST /v1/literature/shared/grants/<id>/revoke         { workspace_id, reason }
  规则：仅 owner_workspace 可 revoke；撤销后立即从所有读路径消失（status='revoked'）
```

---

## 4. 与现有约束的关系

| 现有约束 | 本设计如何满足 |
|---|---|
| workspace 强隔离（astra P0 ②） | **不动** `search_knowledge` 的现有过滤分支；共享走独立并集 |
| 禁硬编码/兜底 workspace | 发布/撤销/grant 全部**必填 ws** 且服务端校验归属 |
| bias 全局共享 | 不受影响（bias 仍走 `library='bias'` 的既有豁免） |
| audit 可追溯 | 发布/授权/撤销都写 `skill_audit` 同款 audit 表（或新建 `shared_audit`） |

---

## 5. 工具侧（agent 可见面）

新增 3 个工具（挂在 `dsh-literature-io`，全部 **workspace_id required**）：

| 工具 | 用途 |
|---|---|
| `literature_publish` | 把一条知识发布到共享池（可选 granted_workspaces） |
| `literature_shared_search` | 检索共享池（默认只读自己有权看的） |
| `literature_unpublish` | 撤销发布 / 收回授权 |

**注意**：`kb_query` **不默认带 shared**——避免"悄悄跨界"，必须显式调 `literature_shared_search`。

---

## 6. 实施步骤（建议顺序）

1. **schema 迁移 v3**：建两张表 + audit（幂等、可回滚）
2. **域层**：`publish_knowledge` / `revoke_publication` / `grant_shared` / `search_shared`
3. **读路径**：`search_knowledge` 加 `include_shared` 参数（**默认 False**，先只加不启用）
4. **HTTP 路由**：3 个端点 + 鉴权（**必须在 `_reject_browser_origin` 之后**，参照本次 0-a 教训）
5. **工具**：3 个新工具 + 前端技能页?? （前端共享管理页另议）
6. **测试**：跨区读被拒 / 发布后可见 / 撤销后消失 / 非 owner 不能撤销

---

## 7. 风险与未决

| # | 风险 | 处置 |
|---|---|---|
| 1 | 读者的检索结果混入共享条目，可能污染判断 | 结果标 `source='shared'` + `owner_workspace`，前端/工具显式展示来源 |
| 2 | 发布方更新原件导致读者看到内容变化 | **这是投影语义的正确行为**；若需快照，另加 `snapshot_rev` 字段记录知识 row_version |
| 3 | `scope='public'` 是否过于宽松 | v1 建议**默认只用 `workspace` + 显式 grant**；`public` 留开关，默认关闭 |
| 4 | 与 deepmemory 记忆的共享如何统一 | 本期只做 literature 知识；memory 侧另议 |
| 5 | 授权方是"会话"还是"用户" | 当前系统无独立用户身份，**以会话 + 工作区为授权主体**；`published_by` 记录会话标识备查 |

---

## 8. 待用户裁定

- [ ] `scope` 是否要 `public`（跨所有工作区可见）？还是 v1 只做显式 grant？
- [ ] 读者删除/归档原件时，发布记录如何处理（级联 revoke？还是保留悬空记录并标 `orphaned`）？
- [ ] 是否需要"发布前审核"（类似 skill 的 review）？
