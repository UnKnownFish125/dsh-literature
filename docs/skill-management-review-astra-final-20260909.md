# skill 管理方案 v0.1 —— astra 独立评审（2026-09-09）

评审者：astra 子 agent（`provider=uuapi-astra / model=gpt-6-astra`）
方法：**独立审核**（prompt 未注入任何其他评审结论）；运行事实来自其拟定、主 agent 代执行的隔离 probe 原始输出；其余注明源码或判断。
验证边界（评审者自述）：真实 FS provider + 临时 SQLite 运行过；**registry 完整构造 / 在线 watcher 延时 / 供应商 prompt cache / 多实例部署 / 实际业务 success 均未运行**，相关说法只作源码或设计推论。未修改方案、生产 DB 或运行中 DSH 配置。

---

## 一、能否落地

能，但只能把当前文档作为方向，**不能原样实施**。

1 周可交付：**受管 skill 登记 / 不可变版本 / 人工审核 / 单机安全发布回滚 / 真实加载计数与人工反馈**。

**不纳入这周**：自动成熟蒸馏、每次 LLM 评分、低分自动归档、多实例。

最大障碍：**没有把"受管版本、DSH 实际加载、实际任务效果"对应起来**。tool-skill 不是任务执行器，加载成功不等于 skill 执行成功。来源不是生命周期；literature 只能是**已收管** skill 的权威源，未登记 GitHub 仍是外部运行态。

## 二、七项核验（证据均来自本机 0.1.2-rc.1）

| 项 | 结论 | 证据 |
|---|---|---|
| **A** | 【源码】正文不是固定 system prompt，但**完整摘要目录会被 createUserMessage 注入**且改变时更新。准确承诺应是"正文按需、摘要目录有成本"，**不能承诺永不击穿缓存**（云缓存未测） | `tool-skill/lib/index.js:203-260,264-285` |
| **B** | 【实测】FS roots rank：项目 `.dsh`100/`.agents`200、自定义 300、用户 dsh400/agents500；provider 同名 5 个 candidate **全部返回**。【源码】最终低 rank 胜出在 `dsh-skill/lib/index.js:312-325,518-520`；**scoped layer 还能覆盖 global**（298-306），不是仅 rank 一个维度。`agentsHome` 由 config→`DSH_AGENTS_HOME`→`homedir/.agents`（FS:78）→ **不能硬编码 `~`**。未运行 registry 完整集成，不把胜出称作运行实测 | FS:78,150-180；registry:312-325 |
| **C** | 【实测】FS 接受并暴露 name/description/whenToUse/invocation/metadata；根级 **version/allowed-tools/permissions 不出现在 get 返回**；**空 body 也被接受**。【推理】新 schema 的兼容/依赖/权限**必须由发布校验器处理**，写到 frontmatter 不自动产生沙箱权限限制；bundle 除 SKILL.md 还可能有资源，**不能丢资产** | FS:679-702,841-874；resourceBase FS:126-132；render 相对路径 `dsh-skill:71-76` |
| **D** | 【源码】`tool-skill:138-156` 只有读取并返回 name/provider/resourceBase/content，**无 version/hash、业务 outcome、直接统计回调**；grep 无 `ctx.emit`/events 输出。`/slug` 走 168-200 直接加载注入，**绕过工具**。不能说宿主无通用事件，只能说**该插件没有所需专用闭环**。需单独适配两条调用路径、幂等事件、准确版本关联；**未知归属保留 unknown**，不能按 slug 把旧版计到新版 | `tool-skill:138-200` |
| **E** | 【实测】临时 DB 删除 `knowledge_items.rating` 后重跑 `install_schema` 仍不恢复列。【源码】`domain:224-225` 只 executescript；`server:117-124` 初始化只调用它；grep 全 server **无 ALTER TABLE / schema_migrations / user_version**。需显式版本迁移，**不能以 CREATE IF NOT EXISTS 替代** | domain:21,224-225；server:117-124 |
| **F** | 【实测】`list_categories('A','global')=[]`；`list_categories('')` 返回 global+A+B；**B 类别可以指定 A 父类别**。【源码】`domain:551-566` **未校验 parent 作用域**；`583-595` ws 筛选与 scope 只 AND。【判断】**默认 workspace 私有，显式审核才能 publish global**；全局可见不等于任何 workspace 可改。复用 categories 需补全局并集读取与父子/引用校验 | domain:551-566,583-595；复盘:125-131 |
| **G** | 【实测】mock vectors 下 `create_knowledge_item(runtime)` 调用 embed_texts 和 add_vectors，`library='skill'` 拒绝 invalid library。【源码】`domain:693-694` API 白名单，`148-159` DB trigger 白名单，`741-763` 自动向量化；`literature_vectors.py:21-24,35-38,86-95` 固定 `literature-server/data/knowledge.faiss`。它是**literature 各 workspace 共用的知识索引**，不是 deepmemory 索引。**独立 skills 表不应调用 knowledge 入库路径**；测试也须 mock 向量模块 | domain:693-694,148-159,741-763 |
| **额外** | 【实测】`lifecycle:archived` 且 chmod 444 **仍被 list**，FS:581-613 **无生命周期/权限位过滤**。退役必须**移出发现根或双禁用 invocation**；单纯"保留只读"无效，**已进入会话的正文也不会被文件删除撤回** | FS:581-613 |

## 三、推荐数据模型：5 张业务新表 + 复用分类 + 1 张迁移表

共同：有 `created_at`，可变表有 `updated_at`；**启用 FK**；**内容版本不可原地改**。

### 1. `skills`
`id`(UUID PK), `slug`, `title`, `category_id`(FK), `scope`(global|workspace), `workspace_id`(nullable), `origin_workspace_id`, `lifecycle`(draft|active|deprecated|archived), `active_version_id`(FK), `row_version`(乐观锁), `created_by`, `created_at`, `updated_at`, `deleted_at`

- `scope=global` 要求 `workspace_id IS NULL`；workspace 要求**真实 UUID 且非空**
- 用 **partial unique** 分别约束 global slug、`(workspace_id,slug)`——**不要用可 NULL 复合 UNIQUE 假装全局唯一**

### 2. `skill_versions`
`id`, `skill_id`(FK), `version`, `parent_version_id`, `skill_md`(含完整 frontmatter), `content_sha256`, `artifact_sha256`, `artifact_uri`, `manifest_json`(资源路径/大小/hash), `source_kind`, `source_url`, `source_ref`(固定 commit), `source_key`(幂等), `distilled_from_json`(memory_id+workspace_id+source revision/hash), `dependencies_json`, `compatibility_json`, `permission_requests_json`, `created_by`, `created_at`；`UNIQUE(skill_id,version)`

- MVP 单文件也保留 manifest 结构；**不支持资源 bundle 时拒绝部署，不悄悄丢脚本**

### 3. `skill_deployments`
`id`, `skill_id`, `target_id`(可信配置解析实例/根), `workspace_id`/`target_scope`, `deployed_path`, `desired_version_id`, `applied_version_id`, `expected_current_hash`, `observed_hash`, `generation`, `state`(pending|applying|verified|failed|drift|removed), `attempt_count`, `next_retry_at`, `last_error`, `last_verified_at`, `operation_key`(UNIQUE), `created_at`, `updated_at`

- 可作为**持久部署任务**，不必本周另造队列
- **DB active 与已生效版本分离**；失败保留目标数据和旧运行版，**不能写 deployed=true**

### 4. `skill_usage_events`
`id`, `producer_id`, `event_key`(UNIQUE with producer), `skill_id`/`version_id`(无法确认时 NULL), `deployment_id`, `observed_content_hash`, `invocation_kind`(tool|slash), `session_id`, `turn_id`, `tool_call_id`, `run_id`, `workspace_id`, `event_kind`(load|apply), `occurred_at`

- 所有计数**从去重事件派生**，不直接 `use_count++`

### 5. `skill_evaluations`
`id`, `skill_version_id`, `usage_event_id`/`run_id`(nullable), `kind`(user_rating|agent_self|task_outcome|approval), `reviewer_id`, `model_id`, `rubric_version`, `score`(nullable), `outcome`(success|failure|unknown|cancelled), `decision`(approve|reject nullable), `evidence_ref`, `comment`, `created_at`

- 用户 1-5 与 agent 0-1 **按 kind 校验，分开聚合**
- 任务 outcome **须有独立证据，不从 agent 自评分推导**

### 6. 复用 `categories`
`id/name/parent_id/scope/workspace_id/order_index/时间`；补**同 scope 父子**或明确受控继承、技能分类引用规则，**删分类不能隐式退役 skill**

### 7. `schema_migrations`
`version` PK, `applied_at`, `checksum`

### 统计口径
`load_count ≠ applied_run_count`。`effectiveness` 只用**已评价的 distinct run** 计算 `success/(success+failure)`，并显示**样本数、版本与观察窗口、评价覆盖率**；无评价为 NULL，`unknown/cancelled` 不算失败；**不要跨用户分数/agent 分数混合平均**。

## 四、1 周路径（3 个 PR，先缩范围）

### D1-D2 / PR1
先固定 scope/slug/回流定义；**显式迁移与 5 表**；读写 API、版本创建、原样 SKILL.md 校验、来源幂等、分类隔离测试；GitHub 固定 commit 进 draft 或显式可信下载快路，**先不自动部署**。deepmemory 仅是 **draft 生产者**，不再维护第二张权威 skills 表。

### D3-D4 / PR2
**单机单写者部署器**；可信 root 配置、遍历/任意符号链接拒绝、**全候选同名冲突检测**、根外 staging、hash 检查、单文件原子替换、**原生解析 + 目标 cwd 实际 list/get 核验**；维护 desired/applied 分离、重试、漂移告警、旧版回滚。**MVP 只承诺单文件 skill**，全 bundle 可靠发布后置或明确拒绝。增加覆盖 tool/slash 的最小观测适配，**version 关联未能证实时只报 unknown，绝不冒充精确版本统计**。

### D5-D7 / PR3
最小管理视图：列表/分类/来源/版本差异/审核/发布状态/人工评价；加载事件幂等、人工 task outcome；`/memory distill` 手动候选→literature draft。验收：冲突拒覆、崩溃重试、回滚、跨区不泄露、**读取只读 archived 仍加载的负向用例**、重复事件不翻倍、两种调用路径、上下文目录增长与新旧版本。**只有发布核验通过并获人工确认才允许源记忆退出召回，失败/撤回须可恢复**。自动 usage≥3 且 7 天无修正、每次 LLM 评分、自动淘汰**均下期**。

## 五、最大 3 条风险

| 级别 | 风险 | 门禁 |
|---|---|---|
| **P0** | **信任/隔离**：GitHub 或工作区记忆直接进全局运行目录，恶意指令与敏感操作细节传播；**声明 permissions 不会生效** | 固定 commit、人工审核/脱敏、默认私有、显式全局发布权限、路径/资源校验（方案:50,52,68；FS:679-702/841-874；复盘:125-131） |
| **P1** | **发布一致性/误加载**：硬编码目录、优先级遮蔽、未受管同名覆盖、半部署及只读假退役；库显示新版本、实际加载旧/另一来源 | 内容 hash + desired/applied、所有候选检查、单写者/原子发布、每目标验证、失败留旧版、**真正移出扫描根**（方案:39,55,70；FS:78,150-180,581-613；registry:312-325） |
| **P1** | **反馈与归档误判**：把加载算成功、仅统计 tool 漏 slash、LLM 自评自产自证、draft 入库就归档记忆造成召回空洞 | 版本/调用路径/去重事件、独立 outcome 且显示 unknown/样本量、无自动淘汰、源记忆归档以**部署验证 + 确认**为门槛并可逆（方案:42,52-55；tool-skill:138-200；旧 deepmemory 方案:31-34,76-82） |

---

## 附：与主 agent 实测的交叉验证

| astra 判断 | 主 agent probe 实测 |
|---|---|
| version/权限字段无语义 | ✅ 静默丢失（`version`/`allowed-tools`/`permissions`） |
| archived 不构成禁用 | ✅ `lifecycle: archived + chmod 444` 仍被 list |
| body 无最短限制 | ✅ 空正文被接受 |
| 副作用全局索引 | ✅ 创建即写 `knowledge.faiss`（单文件共享） |
| 无迁移机制 | ✅ DROP COLUMN 后重跑不恢复 |
| global 分类按区查不到 | ✅ `list_categories('A','global')=[]` |
| 跨区 parent 无校验 | ✅ B 的分类可挂 A 的父 |
