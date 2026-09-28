# 查询范围与越权授权设计（session scope + escalation）

> 日期：2026-09-17
> 需求（用户原话）：**"查询需要权限，会话默认一个范围，越权需要得到指令"**
> 状态：**设计待确认**，未动代码

---

## 0. 现状（已实测）

| 层 | 现状 | 问题 |
|---|---|---|
| **服务端** | `kb/query` 等只校验 `workspace_id` 是合法字符串，**不校验调用方是否有权** | **越权可查**：实测拿 `6e04a6dc`（math-modeling 工作区）的 id 查，**返回 3 条结果** |
| **插件** | `workspace_id` 是**必填参数**，由调用方自己填 | 调用方（agent）可以填**任意**工作区 |
| **会话映射** | `/www/dsh/home/storages/workspace.json` 已有 **10 个工作区 / 57 条会话绑定** | **权威数据已存在**，但没人用 |
| **DSH_SESSION_ID** | 插件里**只有注释提到**，**无解析代码** | "会话默认范围"目前**不存在** |

**⇒ 结论**：现在是"**谁能连上 6260（有 token）就能查任何工作区**"。

---

## 1. 目标模型

```
┌─────────────────────────────────────────────────────────┐
│  会话（session）                                         │
│  ├─ 默认范围 = 该会话所属工作区（来自 workspace.json）      │
│  └─ 已授权范围 = 用户显式指令授予的额外工作区（可过期）      │
└─────────────────────────────────────────────────────────┘
                          │
        查询时：请求的 workspace_id ∈ {默认} ∪ {已授权}
                          │
              ┌───────────┴───────────┐
             是                       否
              │                        │
           放行                  403 + "需要指令"
                                      │
                          agent 转述给用户 → 用户同意
                                      │
                          调 literature_grant_scope 记录授权
                                      │
                                  重试放行
```

**三条规则**：
1. **默认收紧**：不传 `workspace_id` ⇒ 用**会话默认范围**（而非"查全部"）
2. **显式越权**：传了非默认/未授权的范围 ⇒ **403**，并明确告诉 agent"需要用户指令"
3. **授权留痕**：谁授的、授给谁、什么时候过期，全部审计

---

## 2. 数据模型

### 2.1 会话范围绑定

```sql
CREATE TABLE session_scopes (
  session_id     TEXT PRIMARY KEY,        -- DSH 会话 id
  workspace_id   TEXT NOT NULL,           -- 默认范围（权威：workspace.json）
  created_at     REAL NOT NULL,
  updated_at     REAL NOT NULL,
  last_seen_at   REAL
);
```

**填充方式**（两条路，建议都做）：
- **惰性**：首次带 `session_id` 的请求时，服务端回查 `workspace.json` 落库（**不信任客户端传的 ws**）
- **主动**：`POST /v1/literature/session-scopes/sync` 从 `workspace.json` 全量对齐（便于审计）

### 2.2 越权授权

```sql
CREATE TABLE scope_grants (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id     TEXT NOT NULL,
  workspace_id   TEXT NOT NULL,           -- 被授权访问的工作区
  granted_by     TEXT NOT NULL DEFAULT '',-- 授权来源（用户指令原文/操作者）
  reason         TEXT NOT NULL DEFAULT '',
  granted_at     REAL NOT NULL,
  expires_at     REAL,                    -- NULL = 不过期
  revoked_at     REAL,
  UNIQUE(session_id, workspace_id)
);
CREATE INDEX idx_scope_grants_live ON scope_grants(session_id, workspace_id, revoked_at);
```

### 2.3 审计

复用现有 `skill_audit` 的风格，新增 `scope_audit`（或直接复用同一张审计表 + `action` 前缀）：
```
action ∈ {scope.denied, scope.granted, scope.revoked, scope.expired}
```
**每一次拒绝都要记**——被拒的请求正是"有人在试探越权"的信号。

---

## 3. 请求协议

### 3.1 插件侧（`kb_*` / `literature_*`）

```js
// 新增：从 DSH 拿会话 id（此前只有注释，无实现）
const SESSION_ID = String(process.env.DSH_SESSION_ID || '').trim()
// 注意：插件跑在 dsh-web 进程，DSH_SESSION_ID 只在【会话专属进程/agent】里存在。
// 若取不到，则退回「工具调用上下文里的 agent id」——需按 DSH 0.1.5 的 API 确认可用字段。
```

**每个查询类工具**：
```js
async execute(args, exec) {
  const body = { query: ..., mode: ... }
  const ws = String(args.workspace_id || '').trim()
  if (ws) body.workspace_id = ws              // 显式指定 → 交给服务端判权
  body.session_id = resolveSessionId(exec)    // 会话标识（服务端据此判默认范围）
  ...
}
```

**关键**：`workspace_id` 从"必填"改回"**可选**"——
- **不传** ⇒ 服务端用会话默认范围（**这是"默认一个范围"的落点**）
- **传了** ⇒ 服务端判权

### 3.2 服务端判权（统一入口）

```python
def _resolve_scope(handler, session_id, requested_ws):
    """返回 (effective_ws, error)。
    规则：
      - 无 session_id        → 视为「无会话上下文」（CLI/运维），要求显式 ws 且需 admin token
      - 无 requested_ws      → 用会话默认范围
      - requested_ws == 默认 → 放行
      - requested_ws ∈ 有效授权 → 放行 + 记 audit(scope.escalated)
      - 其他                 → 403 {'error': '...', 'need_grant': True, 'workspace_id': ...}
    """
```

**错误响应要能让 agent 自主处理**：
```json
{
  "error": "workspace 6e04a6dc… 不在本会话范围（默认 bf4722bc…）",
  "need_grant": true,
  "workspace_id": "6e04a6dc-56c2-4e06-a58b-fd99674683ef",
  "hint": "如确需访问，请向用户确认后调用 literature_grant_scope"
}
```

### 3.3 新增工具 `literature_grant_scope`

```
literature_grant_scope(workspace_id, reason, ttl_minutes?)
```
**约束**：
- **不能由 agent 自行决定**——`reason` 必须包含**用户指令原文**（或要求调用前先向用户确认）
- 记录 `granted_by = 'user-instruction'` + `reason`
- 默认 **TTL 60 分钟**（`expires_at`），避免"授权一次、永久越权"
- 写 `scope_audit(scope.granted)`

**可选更严**：敏感范围（如含 `bias` 库）要求**二次确认**。

---

## 4. 与现有 ACL 的关系

| 现有 | 本设计 |
|---|---|
| **服务端 workspace 隔离**（写 403 / 读 404） | **不动**——本设计是它**之上的一层"调用方判权"** |
| 读不匹配返回 **404（不泄露存在性）** | **越权仍返回 403**——因为此时"范围"本身是公开信息（会话知道自己的工作区 id），且**需要明确提示 agent 去要指令**（404 会让 agent 以为"不存在"而放弃） |
| `bias` 全局共享 | 保持不变：`bias` **不属于任何工作区**，任何会话都可读（**不受本设计限制**） |
| ACL v0.5 默认隔离 + 显式 permit | 本设计是它的**会话维度补充**（工作区维度已有，会话维度缺失） |

---

## 5. 实施步骤

| # | 内容 | 影响面 |
|---|---|---|
| 1 | schema 迁移 v4：`session_scopes` / `scope_grants` / audit | 幂等迁移，可回滚 |
| 2 | 服务端：`_resolve_scope()` + 接到 `kb/query`、`kb/browse`、`kb/constraints`、`kb/contracts`、`kb/graph`、`literature_search`、`knowledge-browse` | 读路径统一 |
| 3 | 服务端：`POST /session-scopes/sync`（从 workspace.json 对齐） | 新增端点 |
| 4 | 服务端：`POST /scope-grants`（授权）+ `DELETE /scope-grants/{id}`（撤销） | 新增端点 |
| 5 | 插件：解析会话 id（**先确认 DSH 0.1.5 里怎么拿**）+ `workspace_id` 改可选 | 两插件 |
| 6 | 插件：新增 `literature_grant_scope` 工具 | 需 `inject` 已就位 |
| 7 | 前端：技能/知识页显示"当前范围"与"已授权范围"，提供撤销入口 | literature 面板 |
| 8 | 测试：越权被拒 / 授权后放行 / 过期失效 / bias 不受限 | 回归测试 |

---

## 6. 待确认的设计选择

1. **无会话上下文时怎么办**？（CLI 运维、nightly 管线）
   - 选项 A：要求显式 `workspace_id` + 独立 admin token
   - 选项 B：允许"无范围"（等于现状）——**不推荐**
   - **建议 A**

2. **授权粒度**：只到工作区？还是能到 `library`（如"只读 core"）？
   - **建议 v1 只到工作区**，library 级留待后续

3. **TTL 默认值**：60 分钟？还是"会话生命周期内有效"？
   - **建议 60 分钟**（最小惊讶原则）

4. **`bias` 是否完全不受限**？
   - **建议是**（bias 是全局行为约束，任何会话都该看到）

5. **谁算"用户指令"**？
   - 当前系统无独立用户身份 ⇒ `granted_by` 记**会话标识 + reason 文本**
   - 更严的做法：要求在 GUI 里点确认（**需要前端配合**）

---

## 7. 风险

| # | 风险 | 处置 |
|---|---|---|
| 1 | 插件拿不到会话 id（跑在 dsh-web 进程，无 `DSH_SESSION_ID`） | **这是最大不确定**——需先按 DSH 0.1.5 的 API 确认能否从工具 `exec` 上下文拿 agent/session id；拿不到则退化为"服务端按 token 判范围"（弱一档） |
| 2 | 授权疲劳（每次越权都要问用户） | TTL + 前端一键授权；越权是低频操作 |
| 3 | nightly 管线需要跨区 | 管线用独立 admin token，走"无会话"分支（见待确认 1-A） |
| 4 | 破坏了现有 `kb_query` 调用方（ws 必填 → 可选） | 保持**向后兼容**：显式传 ws 仍可用（只是现在要判权） |
