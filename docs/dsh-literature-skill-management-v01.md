# dsh-literature Skill 管理体系设计方案 v0.1（待评估）

日期：2026-09-09　状态：**方案评估中（未实施）**
提出：用户　整理：DSH Agent

---

## 一、需求（用户原话）

> skill 素体如直接从 github 上下载的直接进系统 skill，进过沉淀等优化后进入 literature，
> deepmemory 沉淀产生的直接进入 literature。literature 进行全局 skill 管理，
> 需要基础分类，用户评价，agent 自评，生态周期，使用次数，使用效果。

## 二、三态 skill 体系

```
① 素体层（运行态）                ② 管理层（literature）              ③ 来源
~/.agents/skills/<slug>/SKILL.md   literature.skills
  （DSH tool-skill 直接加载）      （全局 skill 库：分类/评价/生命周期/统计）
      ↑                                 ↑
      │ 部署（优化后，单向）            │ 收录
      └─────────────────────────────────┤
                                        │←── GitHub 素体（下载即用；可选登记）
                                        │←── deepmemory 沉淀（直接收录为 draft）
```

- **系统 skills 目录**：运行态。DSH `dsh-skill-filesystem` 从 `.agents/skills`（或 `.dsh/skills`）
  发现 SKILL.md（frontmatter `name`/`description`），`dsh-tool-skill` 按需加载——**不进 system prompt，不击穿缓存**。
- **literature**：管理态。全局 skill 库，承担分类、评价、生命周期、使用统计与部署。
- **素体**（GitHub 下载）可直接使用；经优化/验证后收进 literature 成为受管 skill。

## 三、数据模型草案（literature 新增 `skills` 表）

| 字段组 | 字段 | 说明 |
|---|---|---|
| 标识 | `id` / `slug`(UNIQUE) / `title` / `description` / `body` / `version` | slug 即 SKILL.md frontmatter name |
| 来源 | `source`(github\|distilled\|manual\|imported) / `source_url` / `source_ref`(commit) / `distilled_from`(JSON 记忆 id) | 溯源 |
| 分类 | `category_id` | 复用现有 `categories` 树 |
| 生命周期 | `lifecycle`(draft\|active\|deprecated\|archived) / `deployed`(0/1) / `deployed_path` / `deployed_at` | |
| 用户评价 | `user_rating`（建议 1-5 星） | 人工 |
| agent 自评 | `agent_self_rating`（0-1） | LLM 打分（蒸馏后 / 使用后） |
| 使用统计 | `use_count` / `success_count` / `fail_count` / `effectiveness`(派生 success/use) | 由 tool-skill 命中回写 |
| 隔离 | `workspace_id`（空=全局） | 见待决策 2 |
| 审计 | `created_at` / `updated_at` / `deleted_at` | 软删 |

## 四、流程

| 流程 | 触发 | 行为 |
|---|---|---|
| **素体导入** | 用户/GitHub 下载 | 直接写 `~/.agents/skills/<slug>/SKILL.md` → 立即可用；可选登记到 literature（`source=github`） |
| **素体优化** | 用户在 literature 编辑/迭代 | literature 记录版本；`active` 后部署回系统目录 |
| **deepmemory 沉淀** | turn-stopping 评估成熟（usage≥3 且 7 天无修正）或 `/memory distill` | 蒸馏 SKILL.md → 写入 literature（`source=distilled`，`lifecycle=draft`） |
| **审核转正** | 用户/agent 审核 | `draft → active` → 部署到系统 skills 目录 |
| **使用回流** | tool-skill 命中 | `use_count += 1`；结果好坏 → `success/fail` |
| **退役** | 用户/低效果自动 | `deprecated → archived`（系统目录移除或保留只读） |

## 五、待决策点

1. **权威源**：A) literature 单一权威（系统目录为部署产物，单向）／B) 双向同步
2. **工作区**：A) skill 全局共享（豁免工作区，同 bias 语义）／B) 按工作区隔离
3. **评价口径**：用户评价 1-5 星 vs 0-1；agent 自评由谁产生（蒸馏时 LLM / 使用后 LLM）
4. **部署方式**：A) literature 主动写系统目录（`deployed` 记录）／B) 导出文件手动放
5. **与知识的关系**：A) 独立 `skills` 表／B) 复用 `knowledge_items` + `library='skill'`

## 六、我方建议

- 1A（单一权威，避免双向冲突）
- 2A（skill 是程序性知识，跨项目复用价值高；同 bias 全局豁免）
- 3：用户 1-5 星；agent 自评在蒸馏后 + 每次使用后由 LLM 打分（0-1）
- 4A（自动部署，失败不回滚库内数据）
- 5A（独立表：skill 有 frontmatter/版本/部署状态，与 knowledge 语义不同）

## 七、待评估问题（请评估者重点回答）

1. **架构合理性**：三态（素体/管理/来源）划分是否成立？literature 作为 skill 权威源是否合适？
2. **数据模型**：`skills` 表字段是否完备？是否缺关键维度（如依赖、兼容 DSH 版本、权限）？
3. **生命周期**：draft/active/deprecated/archived 四态是否够用？是否需要 staged/review 等中间态？
4. **评价体系**：用户评价 + agent 自评 + 使用效果三者如何避免互相污染？评分聚合口径？
5. **部署机制**：literature → 系统目录的单向部署有什么风险（冲突、回滚、多实例）？
6. **与 deepmemory 沉淀管道的关系**：原方案（`deepmemory-skill-distillation-plan.md`）是"记忆→直接写系统 skills"，
   新方案改为"记忆→literature→部署"，评估这个改动的影响。
7. **工作区隔离**：skill 全局共享是否与现有 workspace 隔离语义冲突？
8. **实施顺序**：PR1/PR2/PR3 划分是否合理？有无遗漏的关键路径？
9. **风险清单**：安全（GitHub 下载的素体可能含恶意指令）、质量（LLM 蒸馏 SOP 不可执行）、膨胀、误归档。

## 八、参考

- 现有方案：`/www/deepseek harness workspace/deepmemory-skill-distillation-plan.md`（记忆→技能反馈循环）
- literature 现状：`knowledge_items`（concept/summary/annotation/use_count/rating + 分类树 + 工作区隔离）、
  `categories`（scope=global|workspace 树）、library 取值 bias/core/eco/project/runtime
- DSH skill 基础设施（0.1.2-rc.1）：`dsh-skill` / `dsh-skill-filesystem`（约定 `.agents/skills` 或 `.dsh/skills`）/
  `dsh-tool-skill` / `dsh-skill-badge` / `dsh-client-ui-skill`
