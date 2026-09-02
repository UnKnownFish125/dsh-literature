# dsh-literatum 开发方案 v3.1 —— 面向 agent 的知识库查询服务（deepmemory 派生）

> 版本：plan-v3.1 · 2026-09-01 · **按外部评审（glm）修订**
> 修订说明：v3.1 吸收审核结论 H1-H4（高危）+ M1-M5（应修复）+ 小问题 + Q1-Q5 裁定。
> 定位：literatum 是 deepmemory 派生的、面向 agent 的知识库查询服务——不改 deepmemory 本体，仅作查询通道，由 agent 主动调度。

---

## 0. 一句话

给 DeepSeek Harness 一个 **agent 可主动调用的知识查询服务**：它从 deepmemory 记忆库派生，把 deepmemory 的行为约束（bias）、主体设计/接口契约（core）、生态（eco）、项目（project）等知识组织为可调度、可查询的库，agent 通过工具主动检索，而**不改 deepmemory 一行代码**。

---

## 1. 需求来源（引文核验状态）

| 引文 | 原文 | 核验 |
|---|---|---|
| 1 | "知识库应该面向的是 agent，由 agent 来选择调度" | ✅ sources 逐字命中 |
| 2 | "对 dsh 行为的约束如不要直接动生产机，可以进总行为偏向库" | ✅ sources 逐字命中 |
| 3 | "像 deepmemory 主体，派生插件可能需要访问主体的设计思路或接口契约" | ✅ sources 逐字命中 |
| 4 | "这个插件按道理不涉及修改，只是提供查询服务" | ✅ 本会话用户原话（审核 M2 已口头确认） |
| 5 | "需要配备查询服务主动调用接口" | ✅ 本会话用户原话（审核 M2 已口头确认） |

> M2 处置：引文 4/5 为本会话直接表述（不在 deepmemory 记忆库中属正常，未到抽取时机）；用户已确认确有其言。

---

## 2. 架构（查询服务，派生不自改）

```
DSH Agent (tools: kb_query / kb_browse / kb_constraints / kb_contracts / kb_graph)
        │  /lit-api
        ▼
literatum_server.py (6262 生产 / 6261 测试)   ← 查询聚合层（独立进程、独立鉴权）
        │  读 deepmemory（只读 Bearer token）
        ▼
deepmemory memory-server (6230 生产 / 6240 测试)   ← 知识源（权威存储，分库已上线）
```

**关键约束（v3.1 更新）**：
- literatum **不持有知识副本**，是**查询/聚合代理**
- deepmemory **分库已全量上线**（H1）：search 接受 `library`/`include_archived`、`/v1/memories/libraries` 在线（实测 305 条全 runtime）、bias 触发器校验、archive-library/for-doc/document_links 就位 → **kb 服务直接透传 library，无需任何近似**（Q2 作废）
- **上游路由**（M3）：测试实例读 **6240**、生产读 **6230**（unit 用 env `LITERATUM_MEMORY_URL` 显式配置，防测试流量打生产库）
- **安全**（H4）：服务绑定 **127.0.0.1**（回环），不沿用 deepmemory 的绑定方式也要改到回环——已核实 0.0.0.0 公网可达是真实风险
- **只读边界**（M1）：deepmemory api-token 是全权 token；literatum 持有它即拥有写能力，单机回环下可接受，但契约如实标注此边界，后续可给 deepmemory 加只读 token 档

---

## 3. 核心能力（agent 可调度面）

| 能力 | 语义 | 底层查询（deepmemory 分库已上线） |
|---|---|---|
| **行为约束** | 返回硬性约束（先测试机、不动生产、绝对路径） | `library=bias`（分库契约 P0 已实现） |
| **主体契约** | 查 deepmemory 设计思路、接口契约、架构决策 | `library=core` |
| **生态** | 查派生插件集成点/依赖 | `library=eco` |
| **项目** | 查具体项目进展/决策/commit | `library=project` |
| **通用召回** | 语义检索 + 图谱 | `search` + `graph` |
| **库目录** | 各库条目/主题分布 | `/v1/memories/libraries` |

**存量归类前置（H1 反面）**：实测 305 条存量全在 runtime，bias/core/eco/project 四库为空——kb 服务上线时 `kb_constraints`/`kb_browse` 会查不到东西。**上线前后必须执行存量记忆渐进归类**（分库契约 R5：按 type/importance 自动 + 人工确认），否则 kb 服务空转。

**kb_* 工具唯一归属（M4）**：分库契约 §4.3 原计划在 deepmemory 插件侧做 kb_browse——**裁定为 kb_* 唯一归属 literatum**；deepmemory 插件侧维持 memory_recall/save/briefing 不动，避免双注册。此分工写进两个契约。

---

## 4. 接口契约（冻结）

### 4.1 literatum_server.py（绑定 127.0.0.1，`/v1/literatum/kb/*` 前缀）

| 方法/路径 | 行为 | 底层调用 |
|---|---|---|
| `POST /v1/literatum/kb/query` | `{query, library?, k?, workspace_id?}` → 语义检索 | deepmemory `search`（透传 library） |
| `POST /v1/literatum/kb/recall` | 完整条目（含来源/时间/重要度） | 同 search |
| `GET /v1/literatum/kb/browse?library=` | 库目录（**query 参数**，非 body） | deepmemory `/v1/memories/libraries` |
| `GET /v1/literatum/kb/constraints` | bias 约束独立端点 | deepmemory `library=bias` |
| `GET /v1/literatum/kb/contracts?topic=` | 主体契约/设计文档检索 | deepmemory `library=core` |
| `GET /v1/literatum/kb/graph` | 知识图谱 | deepmemory `/v1/graph/memories` |
| `GET /v1/literatum/health` | 服务健康 + 上游可达性 | deepmemory `/v1/health` |

### 4.2 agent 工具（plugin-v1.js 冻结，kb_* 唯一归属 literatum）

| 工具 | 签名 | 说明 |
|---|---|---|
| `kb_query` | `{query, library?, k?}` | 知识库语义检索 |
| `kb_browse` | `{library?}` | 库目录（调度决策） |
| `kb_constraints` | `{}` | 总行为约束 |
| `kb_contracts` | `{topic?}` | 主体契约查询 |
| `kb_graph` | `{query?}` | 图谱检索 |

### 4.3 鉴权与隔离

- literatum 服务端：`data/api-token` + Bearer（401/403/404）
- **上游 token（M5 修正）**：systemd unit 显式注入
  `Environment=LITERATUM_MEMORY_API_TOKEN_FILE=/www/dsh/home/.dsh-memory-api-token`（已核实与 deepmemory 服务端 data/api-token 同值）
- **上游 URL（M3）**：`Environment=LITERATUM_MEMORY_URL=http://127.0.0.1:6230`（生产）/ `:6240`（测试）
- workspace：透传 `workspace_id`（deepmemory scope_allows 硬过滤）
- **只读纪律**（M1）：仅调用查询类端点；文档标注"持有全权 token，沦陷即写权限"边界

---

## 5. 与 v1/v2（文献库）代码的关系（H3 修正）

**现状（已核实）**：文献库已被并行正名为 **dsh-literature** 并独立部署——`dsh-literature.service` 跑在 6260（`/www/dsh-literature-deploy`），web 插件装进生产+测试 home，agent 工具 `literature_*` 在线。**文献库已另立且在跑**，v3 方案 §5 的"可另立 dsh-literary"已过时。

**处置（v3.1）**：
1. **literature 正式 fork 独立仓库**（保 commit 历史，不从 git 历史+部署副本存活）
2. 本仓库（dsh-literatum）**重写为 kb 查询服务**，删文献库代码
3. **端口**：kb 服务生产 **6262**（6260 已被 literature 占用）、测试 6261（重写版顶替旧测试实例，可沿用）
4. **命名统一（小问题）**：本仓库重写时 package.json/README/服务名统一为 `dsh-literatum`（保留 Gitea 名，Q5 裁定）

---

## 6. 依赖与前置

1. **上游 token**：`LITERATUM_MEMORY_API_TOKEN_FILE` 指向 deepmemory token（生产 `/www/dsh/home/.dsh-memory-api-token` 已有，同值已核）
2. **分库已上线**（H1）：直接透传 library，无近似
3. **存量归类（H1 反面，运营前置）**：bias/core/eco/project 四库为空，需渐进归类
4. **回环绑定（H4）**：literatum 与 literature 服务全部 127.0.0.1
5. **B 测试机先行**：6261（上游 6240）→ A 生产 6262（上游 6230）

---

## 7. 验收标准

1. `kb_query('先测试机')` 返回 ≥1 条含"测试机验证"的约束（实测 id 69 可召回）
2. `kb_constraints` 独立返回 bias 库约束（归类后非空；归类前明确返回空库状态）
3. `kb_browse` 返回库目录，**断言各库计数**（含空库现状说明）
4. `kb_contracts` 检索主体契约类记忆（core 库归类后）
5. 无 deepmemory token → 上游 401 提示（不泄漏 token）；带 token → 全链路 200
6. **端口**：6262/6230 共存；**服务绑定 127.0.0.1，公网不可达**（curl 110.42.10.230:6262 超时）
7. 上游宕机 → 503 明确错误
8. 生产 deepmemory 无任何代码改动（diff 为空）

---

## 8. 开放问题裁定（glm 回答）

| Q | 裁定 |
|---|---|
| Q1 纯代理 vs 缓存 | **纯代理**（deepmemory search 自带 cache，外层缓存引入一致性问题） |
| Q2 分库近似 | **作废**——分库已落地，直接透传 library |
| Q3 只读边界 | **只读正确**，写永远归 deepmemory 本体工具 |
| Q4 UI 取舍 | 纯工具+配置页，查询面板留 P2 |
| Q5 命名 | 保留 Gitea 名 `dsh-literatum`，重写时统一 package.json/README/服务名 |

---

## 9. 实施计划（按审核建议顺序）

| 阶段 | 内容 |
|---|---|
| **S0** | deepmemory 仓库未提交改动先 commit（4 个文件：plugin-v3.js/server.py/client.js/package.json——运维账） |
| **S1** | literature 正式 fork 独立仓库（保 commit 历史） |
| **S2** | 本仓库重写为 kb 服务（127.0.0.1 绑定、6262/6261 端口、上游 6230/6240 env、kb_* 工具） |
| **S3** | 安全加固：dsh-literature 6260 改回环绑定（与 literature fork 同批） |
| **S4** | B 阶段：6261 重写版验证（上游 6240）→ A 阶段：生产 6262（上游 6230） |
| **S5** | 存量记忆渐进归类（bias/core/eco/project），kb 服务"有货" |

---

## 10. 参照

- deepmemory 分库契约：`/www/deepseek harness workspace/harness-memory-archive/docs/deepmemory-library-model-contract.md`（已上线）
- deepmemory kb-query.py（H2：**分工**——CLI 归 deepmemory 仓库自用/运维；literatum kb_* 是 DSH agent 工具层，HTTP 守护+工具注册，定位收窄为"agent 工具注册层"）
- 现有实现（待重写）：`/www/deepseek harness workspace/dsh-literatum/`
