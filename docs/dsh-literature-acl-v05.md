# literature 跨工作区访问 ACL 方案 v0.5

> 2026-09 · 依据：codex/gpt-6-astra 对"默认隔离 + 许可跨区访问"的设计评审（85k tokens 深度）。
> 原则：**默认隔离 + 许可制跨区访问**——默认只见本工作区；跨区访问需显式授权，不能靠"漏校验"获得。
> 现状：v0.3 权限设计（owner/contributor/viewer + 子树只读共享）已定但未落为鉴权；当前 Bearer 只认证服务凭证、workspace 来自请求参数（可伪造）。

---

## 1. 核心模型

**可信身份绑定工作区 + domain 集中授权 + 库级/分类子树级/单知识级只读 ACL。**

- 本区角色：成员身份系统提供（owner/contributor/viewer）
- 跨区：一律走显式 `resource_acl`（默认拒绝，授权才允许**读**）
- 跨区写：一期**只读共享**（B 区建派生知识 + `derived_from` 引用；合入 A 走 A owner 审批）

### 共享粒度（三档）
| 粒度 | 场景 | 说明 |
|---|---|---|
| `library` 库级 | 共用基础（源ws+library 批量） | 批量共享，最常用 |
| `category` 分类子树级 | 科研项目协作 | 含整棵子树 + 主挂知识 |
| `knowledge` 单知识级 | 跨区引用某条 | 只含该条，不沿父子/关系/溯源传播 |

文档/证据/归档独立边界——知识可读**不自动**开放其来源（原文需另行申请）。

### 权限矩阵（一期：跨区只读 viewer）
| 当前角色 | 本区读 | 本区写 | 本区授权 | 跨区读 | 跨区写 | 跨区转授权 |
|---|---|---|---|---|---|---|
| owner | ✅ | 内容/建删树/归档 | ✅ | 有ACL才可 | ❌ | ❌ |
| contributor | ✅ | 新增/编辑/标注（派生走申请） | ❌ | 有ACL才可 | ❌ | ❌ |
| viewer | ✅ | ❌ | ❌ | 有ACL才可 | ❌ | ❌ |

---

## 2. DDL：resource_acl 表

```sql
CREATE TABLE resource_acl (
  id INTEGER PRIMARY KEY,
  owner_workspace_id TEXT NOT NULL CHECK(length(trim(owner_workspace_id))>0),
  grantee_workspace_id TEXT NOT NULL CHECK(length(trim(grantee_workspace_id))>0),
  entity_type TEXT NOT NULL CHECK(entity_type IN ('library','category','knowledge')),
  library TEXT CHECK(library IN ('bias','core','eco','project','runtime')),
  category_id INTEGER REFERENCES categories(id),
  knowledge_id INTEGER REFERENCES knowledge_items(id),
  role TEXT NOT NULL DEFAULT 'viewer' CHECK(role='viewer'),
  granted_by TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL, revoked_at REAL,
  CHECK(owner_workspace_id<>grantee_workspace_id),
  CHECK((entity_type='library' AND library IS NOT NULL AND category_id IS NULL AND knowledge_id IS NULL)
     OR (entity_type='category' AND library IS NULL AND category_id IS NOT NULL AND knowledge_id IS NULL)
     OR (entity_type='knowledge' AND library IS NULL AND category_id IS NULL AND knowledge_id IS NOT NULL))
);
CREATE UNIQUE INDEX acl_library ON resource_acl(grantee_workspace_id,owner_workspace_id,library) WHERE entity_type='library' AND revoked_at IS NULL;
CREATE UNIQUE INDEX acl_category ON resource_acl(grantee_workspace_id,owner_workspace_id,category_id) WHERE entity_type='category' AND revoked_at IS NULL;
CREATE UNIQUE INDEX acl_knowledge ON resource_acl(grantee_workspace_id,owner_workspace_id,knowledge_id) WHERE entity_type='knowledge' AND revoked_at IS NULL;
CREATE INDEX acl_grantee ON resource_acl(grantee_workspace_id) WHERE revoked_at IS NULL;
```

授权只做允许集合并集，不实现 deny/优先级/转授权；授权含自身+后代；单知识不带传播；重叠授权撤销一条不影响其他。

---

## 3. 查询改造示例

```sql
WITH RECURSIVE g AS (
  SELECT * FROM resource_acl WHERE grantee_workspace_id=:ws AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>:now)
), sc(ws,id) AS (
  SELECT c.workspace_id,c.id FROM categories c JOIN g ON g.entity_type='category' AND g.category_id=c.id AND g.owner_workspace_id=c.workspace_id WHERE c.deleted_at IS NULL
  UNION SELECT c.workspace_id,c.id FROM categories c JOIN sc p ON c.parent_id=p.id AND c.workspace_id=p.ws WHERE c.deleted_at IS NULL
), shared(id) AS (
  SELECT k.id FROM knowledge_items k JOIN g ON g.entity_type='knowledge' AND g.knowledge_id=k.id AND g.owner_workspace_id=k.workspace_id
  UNION SELECT k.id FROM knowledge_items k JOIN g ON g.entity_type='library' AND g.library=k.library AND g.owner_workspace_id=k.workspace_id
  UNION SELECT k.id FROM knowledge_items k JOIN sc ON sc.id=k.category_id AND sc.ws=k.workspace_id
)
SELECT k.* FROM knowledge_items k
WHERE k.deleted_at IS NULL AND k.archived=0 AND (k.workspace_id=:ws OR k.id IN (SELECT id FROM shared))
ORDER BY k.id DESC LIMIT :limit;
```

`:ws` 必须来自已验证的活动工作区（可信上下文），非请求参数。

---

## 4. 实施顺序

1. **先建立身份与默认拒绝**：全部 domain 入口要求可信上下文；修复空 workspace、裸 ID、附件、上游旁路；授权中心先实现本区规则及受控 bias；修正 `_v2_call` 异常捕获顺序（PermissionDenied 被 DomainError 提前转 400）。
2. **清理存量边界并加入 ACL**：排查空 workspace、跨区 parent/category、非法来源和关系；落地三档共享、owner 管理接口、到期撤销与授权依据查询。
3. **统一所有读取与约束消费**：list/search/count/graph/subtree/export 共用授权逻辑；修召回截断顺序；插件用当前上下文 + 受控约束来源；引用目标撤权后停止展开。
4. **性能扩展（按需）**：测试后若实时解析成瓶颈，再引入带授权依据的物化集合。

---

## 5. 关键泄漏渠道修复清单（一期必须收口）

| # | 位置 | 问题 | 修复 |
|---|---|---|---|
| 1 | domain:716 | 空 workspace 批量归档作用于全库 | 空值拒绝，不代全库 |
| 2 | domain:593 | subtree 递归不查 workspace/已删/无环 | 约束锚点+每层+输出，校验无环 |
| 3 | domain:346 等 | 按 ID 的 get/update/delete 无调用者上下文 | 统一 `require(ctx, action, resource)` |
| 4 | domain:883 | `_resolve_knowledge_ref` 数字分支不带 workspace | 引用两端同区校验 |
| 5 | domain:818 | bias 约束完全忽略 workspace | 读 bias 与"应用为约束"分开；受控发布 |
| 6 | server:206 | 附件签发按裸 ID 读文档 | 经认证代理下载并复验文档权限 |
| 7 | server:277/312 | 上游 browse/graph 无工作区过滤 | 上游过滤契约 + 校验返回范围 |
| 8 | server:240 | `_v2_call` 异常捕获顺序 | 先捕获更具体异常（PermissionDenied/ConflictError→403/409） |

---

## 6. 与 astra 其余 P0/P1 的关系
- O ② workspace 隔离 = 本方案第 5 节清单（默认隔离兜底 + ACL 许可跨区）
- P1 异常映射 = 第 5 节 #8 + 第 4 节步骤 1
- P1 向量生命周期 / ingest 幂等 = 独立于 ACL，另行批量（本方案不覆盖，但检索截断顺序修正在第 4 节步骤 3）
