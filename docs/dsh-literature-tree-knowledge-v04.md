# literature 树状知识存储方案 v0.4（方案 3：分类树 + 知识分层）

> 2026-09 · 依据：用户选型"3（两者都要）" + 用户原话"记忆只是一小部分，主要是知识，很多知识是树状的"。
> 现状：知识当前是扁平 `knowledge_items` + 图边 `knowledge_relations`，无 category 表、无 parent_id——
> 树状知识（分类挂载 + 层级展开）完全未落地。此方案定义 schema 与 API，供评审后实施。

---

## 0. 核心认知

树状知识 = 两种树的叠加，二者互补、解决不同问题：

| 层 | 树 | 存什么 | 解决 |
|---|---|---|---|
| **A. 分类树** | `categories` 表 | 组织节点（学科/主题/项目/bias 类） | "这条知识**挂**在哪个类别下"——归类导航/权限 |
| **B. 层级知识树** | `knowledge_items.parent_id` | 知识本身的父子（论点→论据→证据） | "这条知识**拆**成什么"——下钻/溯源/论证结构 |

两者关系：**分类树管归属（category_id），层级树管结构（parent_id）**。一条知识既属于某类别，又可以在它自己的层级结构里下钻。

---

## 1. 表结构改动（3 处）

### 1.1 新增 `categories` 表（分类树）
```sql
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  parent_id INTEGER REFERENCES categories(id),   -- 父类别（树）
  scope TEXT NOT NULL DEFAULT 'workspace',        -- workspace(按工作区) | global(bias 全局)
  workspace_id TEXT NOT NULL DEFAULT '',
  node_depth INTEGER NOT NULL DEFAULT 0,          -- 层级深度（可配置上限 category.max_depth）
  order_index INTEGER NOT NULL DEFAULT 0,         -- 同级排序
  created_at REAL NOT NULL, updated_at REAL NOT NULL,
  deleted_at REAL
);
CREATE INDEX idx_cat_ws ON categories(workspace_id, deleted_at);
CREATE INDEX idx_cat_parent ON categories(parent_id);
-- 默认 seed（deepseek-harness）：
--  global/scope=bias: bias
--  workspace/scope=workspace: daily, workspace, core, eco, project
--  bias 全局树一份（跨工作区共享，v0.3 裁决 15）
```

### 1.2 `knowledge_items` 加字段（层级知识树 + 挂载）
```sql
ALTER TABLE knowledge_items ADD COLUMN parent_id INTEGER REFERENCES knowledge_items(id);
ALTER TABLE knowledge_items ADD COLUMN node_depth INTEGER NOT NULL DEFAULT 0;  -- 层级
ALTER TABLE knowledge_items ADD COLUMN node_kind TEXT NOT NULL DEFAULT 'item';  -- root|theory|support|evidence|item
ALTER TABLE knowledge_items ADD COLUMN category_id INTEGER REFERENCES categories(id);  -- 挂到分类树
ALTER TABLE knowledge_items ADD COLUMN node_order INTEGER NOT NULL DEFAULT 0;  -- 同级排序
CREATE INDEX idx_knowledge_parent ON knowledge_items(parent_id);
CREATE INDEX idx_knowledge_cat ON knowledge_items(category_id);
```

**字段语义**：
- `parent_id`：知识内部父节点（B 层）。NULL=根（顶层知识）。
- `node_depth`：在知识树中的深度（根=0，子=1...）。
- `node_kind`：节点角色——`root`(独立知识)/`theory`(论点)/`support`(论据)/`evidence`(证据)/`item`(默认)。
- `category_id`：挂到哪个分类树类别（A 层）。一条知识挂一个主类别（primary，互斥）；跨类补 secondary 走 `evidence_source`/额外表（后续多标签演进，V0.4 先单挂）。
- `node_order`：同级排序（同 parent 下的顺序/优先级）。

### 1.3 `knowledge_relations` 保留（图，不动）
管**可选多对多关联**（支持/反对/引用/派生），与树互补。树决定"归属/层级"，图决定"额外关系"。两者不冲突。

---

## 2. 查询（SQLite 递归 CTE，无需额外表）

```sql
-- ① 取某类别整棵分类树（A 层）：拿该类别全部后代类别
WITH RECURSIVE cat AS (
  SELECT id FROM categories WHERE id = ?
  UNION ALL SELECT c.id FROM categories c JOIN cat ON c.parent_id = cat.id
) SELECT * FROM categories WHERE id IN (SELECT id FROM cat);

-- ② 取某知识节点的整棵子知识树（B 层，含自身）
WITH RECURSIVE kt AS (
  SELECT id FROM knowledge_items WHERE id = ?
  UNION ALL SELECT k.id FROM knowledge_items k JOIN kt ON k.parent_id = kt.id
) SELECT * FROM knowledge_items WHERE id IN (SELECT id FROM kt) ORDER BY node_depth, node_order;

-- ③ 取某类别下的全部知识（A 层归类查询）
SELECT * FROM knowledge_items WHERE category_id = ? AND deleted_at IS NULL;
```

**树 + 向量 + 图如何叠加**：
- 语义检索（FAISS/向量）**先召回候选** → 按 `category_id`/`parent_id` 过滤或按树展开他们的子孙 → 得到"与查询相关的整棵子树"。
- 即：向量管"模糊召回"、树管"层级下钻/展示归属"、图管"关联探索"，三种操作互补。

---

## 3. API 改动（server + domain）

### 分类树（A 层）
- `POST /categories {name, parent_id?, scope, workspace_id}` 创建类别（agent 可申请派生）
- `GET /categories?workspace_id=&scope=` 树形返回（nodes + parent 链）
- `PATCH/DELETE /categories/<id>` 改/删
- `GET /knowledge?category_id=&parent_id=` 知识列表加过滤

### 知识层级（B 层）
- `POST /knowledge` 已支持；加字段 `parent_id / node_depth / node_kind / category_id / node_order`
- `GET /knowledge/<id>` 返回时附带 `children`（SUB TREE）与 `ancestors`（父链）
- `GET /knowledge/<id>/subtree` 整棵子知识树（递归 CTE）

### 权限
- 分类树继承 v0.3 owner/contributor/viewer；`scope='global'`（bias）只读可跨工作区。
- 所有按 id 的读写校验 `workspace_id`（astr P0 修复，见下）。

---

## 4. 迁移脚本要点（存量 97 条知识）

```sql
-- 存量知识无层级/无类别：默认全为根(root, depth=0)，category_id=关联到 runtime/category
-- 建立默认类别根（bias/daily/workspace/core/eco/project）
INSERT INTO categories (...) SELECT 'bias', NULL,'global','',0...
-- 存量知识 category_id 按 library 归到对应默认类（bias→bias, core→core, ...）
-- parent_id 全 NULL、node_depth=0、node_kind='item'
```
不动现有数据内容，只补默认归类。

---

## 5. 与 astra 审核 P0/P1 的关系

本方案**先解决"树状知识存储"（结构层）**，astra 的 P0/P1 主要在上层（鉴权/workspace 隔离/向量生命周期/幂等）——两者独立、可先后修。建议顺序：
1. **结构层**（本方案）：树状 schema + API + 迁移（知识是主体，先把它装进正确的结构）
2. **安全层**（astra P0）：workspace 强隔离（所有按 id 查询补 workspace 条件）+ 鉴权/附件修复
3. **一致性层**（astra P1）：向量生命周期 + 检索过滤 + ingest/nightly 幂等

---

## 6. 待你确认（3 点）

1. **多标签**：本方案 V0.4 先**单挂**（一知识一个 category_id），跨类/科研重叠的未来用 secondary 表——还是现在就做多挂？你之前说"允许跨类，科研领域重叠"，但那是 v0.3 理想；实际我建议 V0.4 先单挂保稳，多标签二期。
2. **层级深度上限**：`category.max_depth` 默认 3？建议 3~4，防无限下钻。
3. **node_depth 是否冗余存**：冗余（查询快）但需维护；或不冗余（靠 CTE 算）。我建议**冗余存**（知识树相对稳定，改挂/移动少），配合更新时重算子树深度。
