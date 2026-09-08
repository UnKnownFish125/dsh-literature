# 复盘：`deepseek-harness` 假工作区——服务侧根因与修复

日期：2026-09-09　范围：dsh-literature（6260）/ deepmemory 记忆插件 / kb-plugin
状态：**根因已定位，literature 侧已修复并验证；deepmemory 侧待决策**

> 关联：调用方复盘 `/data/math-modeling-2026/references/WORKSPACE_SCOPE_POSTMORTEM.md`（记录了 139 条知识 / 49 条记忆写错库）。
> 本文回答**更深一层的问题**：为什么服务里会存在一个不存在的"工作区"。

---

## 一、结论

`deepseek-harness` **从来不是 DSH 的工作区**——它是 literature/deepmemory **自己造出来的默认字符串**。
DSH 的真实工作区只有三个 UUID（`workspace.json`）：

| 工作区 | title | path |
|---|---|---|
| `bf4722bc-37d2-438f-b5dd-598d24a13cf5` | deepseek harness selfcontrol | `/www/deepseek harness workspace` |
| `2d98a449-244b-460c-bee0-db2d1783bb10` | Minecraft | `/data/Minecraft` |
| `6e04a6dc-56c2-4e06-a58b-fd99674683ef` | math-modeling-2026 | `/data/math-modeling-2026` |

所有写进 `deepseek-harness` 的数据都落在**没有对应 DSH 项目**的孤儿命名空间里。

---

## 二、根因链（服务侧，5 环）

### 环 1：起源——默认值是"拍脑袋"的，不是从宿主读的

早期 `kb_server` 写了 `DEFAULT_WORKSPACE = "deepseek-hardness"`（拼写错误 + 自造值）。
当时项目没有"工作区标识以宿主 `workspace.json` 为唯一真相"的约定。

### 环 2：只修了拼写，没质疑值本身（commit `2ee2ed7`）

```
fix: kb_server DEFAULT_WORKSPACE 拼写 deepseek-hardness→deepseek-harness
```

同时把 data 里 307 条记录的 `workspace_id` 从 `deepseek-hardness` 迁到 `deepseek-harness`。
**问题被"修正"成了另一个问题**：值仍然不对应任何真实工作区，但因为写入/读取都用同一个值，
系统自洽——**错误被自洽性掩盖了**。

### 环 3：默认值扩散到 6 处（无单一权威来源）

| 位置 | 形态 | 后果 |
|---|---|---|
| `literature_upstream.py:22` | `DEFAULT_WORKSPACE` 兜底 | 请求不带 ws 时查错库 |
| `literature_ingest.py:85` | `run_once(workspace_id="deepseek-harness")` | 只拉/写孤儿库 |
| `literature_ingest.py:100` | `--workspace-id` argparse default | 同上 |
| `literature_nightly.py:265` | **硬编码传给 `process_archive_batch`** | **夜间加工空转**（见环 4） |
| `literature_relations.py:61` | 建关系边硬编码 | 关系边归属错库 |
| `kb-plugin/plugin-v1.js:36,54` | 工具 schema `default` | **被调用方抄成"目标值"**（事故直接源头） |
| deepmemory `plugin-v3.js:51` | `let WORKSPACE = 'deepseek-harness'` | 所有会话记忆进孤儿库 |

### 环 4：夜间加工长期空转（隐藏故障）

`literature_nightly.py:265` 用 `workspace_id="deepseek-harness"` 过滤 raw 归档，
而归档实际归属真实 UUID → **查询永远为空**。实测：

```
journalctl -u dsh-literature-nightly (09-08 03:31)
  "archive_processed": 0        ← 空转
```

隔离测试（修复前后对比）：

```
修复后（不传 ws）能取到: [(1,'6e04a6dc-56c'), (2,'bf4722bc-37d')]
修复前（传 deepseek-harness）能取到: []
```

即：**归档层 → 知识层的主通道实际上没在工作**，只是没有报错，长期静默。

### 环 5：前端修好后，孤儿数据"消失"才暴露

literature 前端早期在 workspace 解析失败时也回落到同一个默认值，所以面板能显示数据。
codex 修复 `resolveWorkspaceId`（改用宿主 shell services 按会话解析真实 UUID）后，
前端开始用真实 UUID 查询 → 孤儿库里的数据"看不见了" → 问题暴露。

**这是一个典型的"修复暴露了更早的错误"**：前端变对了，错误的数据归属才显形。

---

## 三、为什么调用方会踩坑（工具设计缺陷）

复盘报告说"抄了 `kb_query` 工具 schema 的 default"——**根因在工具设计**：

1. **`default` 被当业务目标值**：schema default 本意是"调用方未提供时的兜底"，但它长得像"推荐值"，
   调用方（脚本）直接抄走。
2. **写入工具没有归属校验**：`memory_save` 甚至没有 `workspace_id` 参数（插件硬编码），
   调用方**无法**指定正确工作区，只能被动接受兜底值。
3. **写完没有归属断言**：139 条写完后做了 10/10 校验，但只校验"条数/可检索"，没校验"落在哪个库"。

---

## 四、影响

| 对象 | 影响 | 处置 |
|---|---|---|
| 139 条数模知识 | 落在孤儿库，项目视图不可见 | ✅ 已迁移到 `6e04a6dc`（math-modeling-2026），实测可查 |
| 67 条历史归档/知识 | 落在孤儿库 | ✅ 已迁移到 `bf4722bc`（09-08） |
| 49 条数模记忆 | 仍在 deepmemory 孤儿库 | ⏳ 待决策（需改插件 + 重启 dsh-web） |
| 夜间加工 | 长期空转 | ✅ 已修复（不再过滤假工作区） |
| 数据完整性 | 无损坏，仅归属错 | — |

---

## 五、literature 侧修复（已实施）

| 修复 | 文件 | 说明 |
|---|---|---|
| 夜间加工不再过滤假工作区 | `literature_nightly.py` | 去掉 `workspace_id="deepseek-harness"`；每条归档按其自身 `workspace_id` 加工 |
| ingest 默认拉全部 | `literature_ingest.py` | `workspace_id` 默认空=全部工作区（各条按自身归属）；`--workspace-id` 帮助文本说明 |
| 关系边归属跟随知识 | `literature_relations.py` | 建边用 `ws.get(kid)`（知识自身归属），不写死 |
| bias 注入去硬编码 | `kb-plugin/plugin-v1.js` | 全局 bias 不传 `workspace_id` |
| 工具 default 去除 | `kb-plugin/plugin-v1.js` | `kb_query.workspace_id` 不再给假默认值，描述写明"写入请按会话解析" |
| 工作区列表全量 | `literature_domain.py` | `/workspaces` 列出宿主全部工作区（含 title），前端可切 |

验证：14 单测绿；隔离测试证明 nightly 修复前空转/修复后正常。

---

## 六、防再犯（服务侧）

1. **workspace_id 单一权威来源**：只认 `/www/dsh/home/storages/workspace.json` 的 `workspaceId`（UUID）。
   任何服务默认值都不得作为写入目标。
2. **写入路径必须显式归属**：服务端拒绝空 workspace 的写入（`archive_knowledge_library` 已如此）。
3. **`default` 只当兜底**：工具 schema 的 default 不得复制为业务目标值；文档里显式标注"兜底值"。
4. **加工链路按数据自身归属**：ingest/nightly/relations 一律用记录自带的 `workspace_id`，
   禁止全局默认值参与写入。
5. **写入后归属断言**：批量写入后必须校验「目标工作区 +N、来源工作区 +0」。
6. **静默故障要告警**：nightly 输出 `archive_processed: 0` 应触发告警，而不是当作正常。

---

## 七、待决策

1. **deepmemory 侧记忆归属**（49 条数模记忆 + 全库记忆）：
   需改 `plugin-v3.js` 增加"按会话解析工作区"（与 literature 前端同口径），
   并重建已错落的记忆。**改插件后需重启 dsh-web（需授权）**。
2. `literature_upstream.py` 的 `DEFAULT_WORKSPACE` 兜底值是否改为空
   （影响 `kb/query`、`kb/contracts` 未传 ws 时的行为，属读取路径，非本次事故直接原因）。
