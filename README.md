# dsh-literature — 文献 · 证据 · 知识管理插件

给 DeepSeek Harness 的「文献管理器 + 证据库 + 书本知识库」三合一独立插件。
管理论文/PDF/引用，维护「主张—证据—论文」的论证链，把书本阅读沉淀成可检索的知识网络。

> 定位：**独立插件**（deepmemory 派生，但不并入 dsh-deepmemory）。
> 复用 deepmemory 的部署/鉴权/代理范式，存储与 API 完全独立（独立 sqlite、独立端口 6260）。

---

## 核心模型

```
Document（文献/书本，统一实体）
 ├─ type: paper | book | report | web
 ├─ metadata: title/authors/year/journal/DOI/ISBN/url
 ├─ attachment: PDF/EPUB 路径（可选）+ sha256
 ├─ read_status / lifecycle_status
 └─ sections: 章节/页面锚点（供证据溯源）

Evidence（证据，从文献可定位处提取）
 ├─ claim / stance (supporting|contradicting|contextual)
 ├─ evidence_text（带文献+章节定位）
 └─ mapped_document → Document

KnowledgeItem（知识条目，书本/多文献形成）
 ├─ concept（概念名，如"认知负荷"）
 ├─ summary / notes
 ├─ relations: [KnowledgeItem.id → KnowledgeItem.id, 关系词]（概念网络边）
 └─ sources: [Evidence.id...]（溯源）
```

**派生链**：`Document →(提取)→ Evidence →(归纳)→ KnowledgeItem →(关联)→ 概念网络`

全部实体支持**软删**（`deleted_at`），**workspace_id 硬过滤**（联结表经两端推导，跨工作区数据绝不串扰）。

---

## 架构

```
DSH Web (client.js) ──/lit-api──> Host (index.js, prefix 代理, Bearer token)
                                       │
                 literatum_server.py (6260, sqlite + FTS + 附件落盘 + 鉴权)
                                       │
                  literatum_domain.py（域模型 + CRUD + 图谱 + 导入导出 + 去重）
```

| 组件 | 路径 | 说明 |
|---|---|---|
| 服务端 | `literatum-server/literatum_server.py` | HTTP 路由（21 个端点），鉴权沿用 deepmemory（api-token + Bearer + 拒 Origin） |
| 域层 | `literatum-server/literatum_domain.py` | 模型/CRUD/软删/图谱/导入导出/去重/附件登记，独立 sqlite |
| Web 插件 | `web-plugin/` | `/lit-api` 全量代理 + 文献库 UI + 插件配置页（设置→插件→插件配置） |
| Agent 工具 | `agent-preset/literatum-plugin/plugin-v1.js` | `literatum_add` / `literatum_search` / `literatum_attach` / `literatum_link_evidence` |
| 契约 | `docs/dsh-literatum-contract.md` | contract-v0.2（冻结接口，多子代理开发依据） |

### 技术栈

- **Python**：标准库 `sqlite3` + `http.server`（无第三方框架）；FTS5 trigram 中文分词
- **Node**：`@deepseek-ai/schemastery`、`@deepseek-ai/dsh-settings`（web 插件）
- 附件存储：`<deploy>/data/attachments/`；取回用 HMAC 短期签名 token（5 分钟）

---

## API 概览（`/v1/literatum/*`，经 `/lit-api` 代理）

| 方法/路径 | 行为 |
|---|---|
| `POST /documents` / `GET /documents?q=&workspace_id=` / `GET /documents/<id>` / `PATCH` / `DELETE` | 文献 CRUD（FTS 检索 + workspace 硬过滤） |
| `POST /evidence` / `GET/PATCH/DELETE /evidence/<id>` / `POST /claims?q=` | 证据 CRUD + 同一主张聚合（support/contradict） |
| `POST /knowledge` / `GET/PATCH/DELETE /knowledge/<id>` / `GET /graph?workspace_id=` | 知识条目 CRUD + 概念网络（id 对口径） |
| `POST /import/bibtex` / `POST /import/doi` / `POST /dedupe` / `GET /export/bibtex` | 导入（BibTeX/Crossref DOI）+ 精确去重 + 导出 |
| `POST /attachments` / `GET /attachments/<file>?t=` | 附件上传（multipart）+ 签名取回 |
| `GET /config-schema` / `GET|POST /config` | 插件配置页数据源 |

### 鉴权

- 服务端：`data/api-token`（首次启动自动生成）；`Authorization: Bearer <token>`，缺失/不匹配 401；带 `Origin` 头 403；根路径 404
- Host 代理：从 `LITERATUM_API_TOKEN_FILE` env / `$DSH_HOME/.dsh-literatum-api-token` 读取并附加

---

## 安装与部署

### 测试机先行（B 阶段）

```bash
# B0: 建目录 + 复制服务端
mkdir -p /www/dsh-test-literatum
cp literatum-server/{literatum_domain.py,literatum_server.py} /www/dsh-test-literatum/

# B1: systemd（测试机 6261）
cat > /etc/systemd/system/dsh-test-literatum.service << 'EOF'
[Service]
Type=simple
WorkingDirectory=/www/dsh-test-literatum
Environment=HOME=/root
Environment=LITERATUM_SERVER_PORT=6261
ExecStart=/opt/AstrBot/venv/bin/python3 /www/dsh-test-literatum/literatum_server.py
Restart=on-failure
EOF
systemctl daemon-reload && systemctl enable --now dsh-test-literatum.service

# B3: 验证
TOKEN=$(cat /www/dsh-test-literatum/data/api-token)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:6261/v1/literatum/documents
```

### 生产同步（A 阶段，B 全通过后）

```bash
mkdir -p /www/dsh-literatum-deploy/literatum-server
cp literatum-server/{literatum_domain.py,literatum_server.py} /www/dsh-literatum-deploy/literatum-server/
# systemd dsh-literatum.service，LITERATUM_SERVER_PORT=6260

# web 插件 → 生产 home
mkdir -p /www/dsh/home/profiles/web/node_modules/dsh-literatum
cp web-plugin/{index.js,client.js,package.json,dsh.patch.yml} /www/dsh/home/profiles/web/node_modules/dsh-literatum/
python3 scripts/fix-client-bundle.py /www/dsh/home/profiles/web/node_modules/dsh-literatum/client.js dsh-literatum

# agent 工具
mkdir -p /www/dsh/home/.agent-presets/_literatum-plugin
cp agent-preset/literatum-plugin/plugin-v1.js /www/dsh/home/.agent-presets/_literatum-plugin/

systemctl daemon-reload && systemctl restart dsh-literatum.service dsh-web.service
```

> 端口基线：生产 6260 / 测试机 6261；与 deepmemory（6230/6240）、task-board（6250）互不冲突。
> 部署顺序严格「先测试机（B）→ 生产（A）」。

---

## 测试

```bash
cd literatum-server
python3 -m unittest tests.test_literatum -v   # 8 个测试：域层 + HTTP + 附件安全
```

覆盖：CRUD/软删、claims 聚合、图谱 2 节点 1 边、workspace 隔离、BibTeX 导入去重导出、附件上传/签名取回/坏 token/过期/路径穿越、鉴权 401/403/404。

---

## 开发

- 契约即接口：`docs/dsh-literatum-contract.md`（contract-v0.2，SA 间 frozen 接口）
- 多子代理分工：SA-1 域层 → SA-2 服务 → SA-3 插件 → SA-4 图谱/检索增强
- 派生参照：deepmemory `memory-server/server.py`（鉴权/路由模式）、`dsh-livetaskboard`（插件骨架）

## 许可

AGPL-3.0-only（与派生源 dsh-deepmemory 一致，见 [LICENSE](./LICENSE)）

## 知识库查询（kb 体系）
- `kb-server/`：知识查询服务（6262，代理 deepmemory 只读）
- `agent-preset/kb-plugin/plugin-v1.js`：kb_query / kb_browse / kb_constraints / kb_contracts / kb_graph 五工具
- 文档：`docs/dsh-literature-kb-dev-plan.md`（模型 v0.3 演进中）
