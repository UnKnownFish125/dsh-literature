# dsh-literature — 完整知识库与归档体系

DeepSeek Harness 的 **知识库 + 归档中枢**插件：管理「原料 → 归档 → 加工 → 知识」全生命周期，
与 deepmemory 专属对接（deepmemory 是原料来源之一，literature 是知识的组织者）。

> 定位：独立插件（deepmemory 派生，不并入 dsh-deepmemory）。
> 复用 deepmemory 的部署/鉴权/代理范式，存储与 API 完全独立（独立 sqlite、独立端口 6260）。

---

## 分层体系（v0.3+）

```
原料层（收）
 ├─ 文献/文档（import bibtex/doi/附件）
 └─ deepmemory 专属对接（export-archive → 记忆+原始对话作为原料）

归档层（存原文，不向量化，可溯源）
 ├─ memory_archive（deepmemory 原料归档：memory_id 溯源锚点 + sources 脱敏原文）
 └─ documents / evidence（文献原文 + 证据，位置可配置 archive.dir）

加工层（夜间）
 ├─ literature_nightly.py（deepseek 低谷价 + flash-0731 经 uuapi）
 └─ raw → knowledge（带 source_memory_id 溯源，可读的中文提炼）

知识库（检索）
 ├─ knowledge_items（concept/summary/notes + 批注/使用次数/评分）
 ├─ categories（分类树，动态可配置深度；bias=global 全局，其余按工作区）
 ├─ parent_id / node_depth / node_kind（知识内部父子层级）
 ├─ knowledge_relations（关系边：相关/影响 等）
 └─ FAISS jina 768 维向量（独立索引，语义检索 RRF 融合 FTS）
```

**派生链**：`原料(记忆/文献) → 归档(原文+锚点) → 加工(夜间LLM) → 知识(树+向量) → 检索(RRF)`

---

## 工作区与全局约束

| 维度 | 规则 |
|---|---|
| **知识** | 按 `workspace_id` **隔离**（各工作区只见自己知识）；读写按 ID 均校验（跨区 403/404） |
| **bias** | **全局行为约束库**（v0.3 裁决 15）：任何工作区可见全部 bias，**不计入知识条数统计** |
| **统计** | `count/workspaces` 只算**非 bias 且未归档**知识 |
| **跨区访问** | 默认隔离 + 许可制 ACL（`resource_acl`，一期只读 viewer，见 `docs/dsh-literature-acl-v05.md`） |

---

## 架构

```
DSH Web (client.js) ──/lit-api──> Host (index.js, prefix 代理, Bearer token)
                                       │
           literature_server.py (6260, sqlite + FTS + FAISS + 附件 + 鉴权)
                                       │
            literature_domain.py（域模型 + CRUD + 图谱 + 分类树 + 隔离）
                                       │
         literature_upstream.py（deepmemory 上游只读，6260 供 kb 查询）
```

| 组件 | 路径 | 说明 |
|---|---|---|
| 服务端 | `literature-server/literature_server.py` | HTTP 路由（kb/query、kb-search、documents、knowledge、categories、graph、archive-ingest/count、attachments 签名下载） |
| 域层 | `literature-server/literature_domain.py` | 模型/CRUD/软删/图谱/分类树/树状知识/工作区隔离/bias 全局 |
| 向量 | `literature-server/literature_vectors.py` | FAISS jina 768 维（IndexFlatIP+IndexIDMap） |
| 夜间加工 | `literature-server/literature_nightly.py` | raw→knowledge（flash-0731，低谷价） |
| 原料 ingest | `literature-server/literature_ingest.py` | deepmemory export-archive → memory_archive（幂等去重） |
| 自动关系 | `literature-server/literature_relations.py` | 向量相似度 → knowledge_relations 边（岛群图谱数据基础） |
| 文件爬取 | `literature-server/literature_upstream.py` | deepmemory 上游只读共享层 |
| Web 插件 | `web-plugin/`（client.js 四视图 + /lit-api 代理） | 文档/知识/图谱/状况 + 配置页 |
| Agent 工具 | `agent-preset/kb-plugin/plugin-v1.js` | kb_query/browse/constraints/contracts/graph/archive_library |

### 技术栈
- **Python**：标准库 `sqlite3` + `http.server`；FTS5 trigram；FAISS（向量）
- **Node**：`@deepseek-ai/*`（web 插件）；CJS + React.createElement（无 JSX）
- 附件存储：`data/attachments/`；HMAC 签名 token（5 分钟 TTL）；附件路由仅凭签名（window.open 可用）

---

## API 概览（`/v1/literature/*`，经 `/lit-api`）

| 方法/路径 | 行为 |
|---|---|
| `POST /documents` / `GET /documents?q=&workspace_id=` / `GET/PATCH/DELETE /documents/<id>` | 文献 CRUD（FTS 检索 + workspace 硬过滤） |
| `POST /evidence` / `GET/PATCH/DELETE /evidence/<id>` | 证据 CRUD（含 zh_content 中文对照） |
| `POST /knowledge` / `GET/PATCH/DELETE /knowledge/<id>` | 知识 CRUD（含 annotation/use_count/rating + 树字段） |
| `GET /knowledge/<id>/subtree` | 知识子树（递归 CTE） |
| `POST /knowledge/<id>/use` / `/rate` | 使用次数 / 评分 |
| `GET /categories` / `POST /categories` / `PATCH/DELETE /categories/<id>` / `GET /categories/<id>/subtree` | 分类树 CRUD + 子树 |
| `GET /kb-search` / `POST /kb/query` | 语义检索 / N3 hybrid（本地知识+deepmemory RRF） |
| `GET /kb/browse` / `constraints` / `contracts` / `graph` | deepmemory 目录 / bias 全局约束 / 契约 / 上游图谱 |
| `GET /knowledge-browse` / `knowledge-count` / `workspaces` | 本地知识枚举（含归档）/ 计数（排除 bias）/ 宿主工作区（含 title） |
| `POST /archive-ingest` / `GET /archive-count` / `archive-memories` | 原料归档 ingest/枚举/计数 |
| `POST /archive-library` | 库级归档（要求 workspace_id，bias 拒归档） |
| `POST /attachments` / `GET /attachments/<file>?t=` | 附件上传 / 签名取回（仅凭签名） |
| `GET /documents/<id>/attachment-url` | 生成签名下载 URL |
| `GET /graph?workspace_id=&library=` | 知识图谱（library 过滤 + bias 全局节点） |
| `GET /config-schema` / `GET|POST /config` | 插件配置页数据源 |

---

## 安装与部署

### 生产（6260 单服务）
```bash
mkdir -p /www/dsh-literature-deploy/literature-server
cp literature-server/*.py /www/dsh-literature-deploy/literature-server/
# systemd dsh-literature.service，LITERATURE_SERVER_PORT=6260
#   LITERATURE_MEMORY_URL=6230（deepmemory 上游） + LITERATURE_MEMORY_API_TOKEN_FILE
# web 插件 → vendored：
#   /www/dsh/home/profiles/web/node_modules/.pnpm/dsh-literature@*/node_modules/dsh-literature/
```

### 测试机（6263 隔离）
`dsh-test-literature.service`，`LITERATURE_SERVER_PORT=6263`，上游 6240（deepmemory 测试）。

### 验证
```bash
TOKEN=$(cat data/api-token)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:6260/v1/literature/knowledge-count?workspace_id=<host-ws>
```

---

## 关键决策文档
- `docs/dsh-literature-model-v03.md` — 分层体系 + 分类树 + 权限设计
- `docs/dsh-literature-tree-knowledge-v04.md` — 树状知识（方案3：分类树 + 知识分层）
- `docs/dsh-literature-acl-v05.md` — 跨工作区访问（默认隔离 + 许可 ACL）
