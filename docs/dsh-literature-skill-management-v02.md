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

## 七、待确认决策点（少数）

| # | 决策 | 我的建议 |
|---|---|---|
| 1 | **部署目标根** | 专用受管目录（如 `/www/dsh/skills-managed`）+ 通过 `customSkillDirs`(rank 300) 注册；**不用** `~/.agents/skills`(500，易被项目遮蔽) |
| 2 | **首周是否含自动部署** | 含（PR2），但**单机单写者 + 人工触发**；多实例下期 |
| 3 | **skill 默认 scope** | 默认 `workspace` 私有；publish global 需显式批准 |
| 4 | **MVP 是否支持 bundle** | 不支持——明确拒绝，避免静默丢脚本 |
| 5 | **是否本周接 deepmemory 蒸馏** | 只做**手动** `/memory distill` → draft；自动成熟判定下期 |

## 八、参考

- v0.1 方案：`docs/dsh-literature-skill-management-v01.md`
- astra 独立评审（最终）：`docs/skill-management-review-astra-final-20260909.md`
- astra 评审（首轮，无工具版）：`docs/skill-management-review-astra-20260909.md`
- 子 agent 工具调用问题：`docs/dsh-subagent-toolcall-issues.md`
- 事故复盘：`docs/dsh-literature-workspace-scope-postmortem.md`
- 记忆：`#691`（子 agent 工具规范）、`#692`（DSH skill + literature 实测事实）
