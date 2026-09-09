# 子 agent 工具调用问题记录（2026-09-09）

背景：用 astra 子 agent（`provider=uuapi-astra / model=gpt-6-astra`）审核 skill 管理方案时，
出现"工具调用老是出问题"，实测定位到**两个 prompt/工具交互缺陷**。

---

## 问题 1：bash 工具 schema 让模型填 `sandbox_permissions` → 预检失败 → 死循环

### 现象（实测，子 agent 会话 `1247c9dd-b000-46e9-a2e2-815d1149d2f9`）

18 次工具调用中 **5 次失败，全部是 bash**，且都是同一个 `pwd` 反复重试：

```
step3 bash {"command":"pwd","description":"Confirm the current workspace directory","justification":"","run_in_background":false,"sandbox_permissions":"danger-full-access"}   ✗
step4 bash {"command":"pwd",...,"justification":"Confirm the workspace path without changing files.",...,"sandbox_permissions":"danger-full-access"}                       ✗
step5 bash {"command":"pwd",...,"justification":"This only confirms the current workspace path.",...}                                                                     ✗
step6 bash {"command":"pwd",...,"justification":""}                                                                                                                        ✗
step7 bash {"command":"pwd",...,"justification":""}                                                                                                                        ✗
```

### 报错原文

```
Error: invalid justification: expected a non-empty sentence
Error: sandbox escalation to "danger-full-access" is not strictly wider than this call's current "danger-full-access" mode
```

### 根因

1. `dsh-tool-bash` 的参数 schema 里**包含** `sandbox_permissions` 与 `justification`
   （`dsh-tool-bash/lib/index.js:286` 定义，`:123` 有 `validateEscalationArgs`）。
2. 强模型（gpt-6-astra）**倾向于把 schema 里的参数全部填上**——它自己诊断：
   > "当前 bash 调用被工具 schema 自动包含 sandbox_permissions 导致普通 pwd 多次预检失败（非文件权限拒绝）"
3. 当前会话**已经是 `danger-full-access`**（最高模式），传该参数必然触发
   "not strictly wider" 预检失败；`justification` 为空时再叠加 "invalid justification"。
4. 结果是**模型陷入重试循环**，无法执行任何 bash → 只能读文件，拿不到"运行实测"。

### 影响

- 子 agent 的实测能力被废掉（只剩 read/glob/grep）
- 每次失败都消耗一个 step（本例 8 个 step 里 5 个浪费在同一个 pwd）
- 任何"强模型 + bash"的子 agent 场景都会踩到

### 修复建议

**A（推荐，根治）**：`dsh-tool-bash` 在"请求的模式 ≤ 当前模式"时**静默忽略** `sandbox_permissions`，
而不是报错——因为此时本就没有更宽模式可升，参数无意义。
同时 `justification` 仅在真正需要 escalation 时才校验。

**B（权宜）**：在派发子 agent 的 prompt 里明确声明：
```
调用 bash 只传 command + description，不要传 sandbox_permissions / justification
（当前会话已是 danger-full-access，传了会被预检拒绝）
```

---

## 问题 2：派发子 agent 的 prompt 未声明工具参数约束（放大问题 1）

### 现象

首次派发时 prompt 只写了任务与材料，**没有说明工具参数约束**，
于是模型按自己的习惯填满 schema → 直接踩中问题 1，5 次重试全部浪费。

### 根因

prompt 只描述"要做什么"，没有描述"这台机器的工具怎么用"。
子 agent 与主 agent 的工具集相同，但**子 agent 没有主 agent 的系统提示**
（主 agent 的系统提示里有"approval prompts are disabled … do not set sandbox_permissions"，
子 agent 未必继承这条约束）。

### 修复建议

派发子 agent 的 prompt 增加固定段（模板）：

```
【工具调用约定】
- bash 只传 command + description；不要传 sandbox_permissions / justification
- read 的 limit 不传（默认 2000 行）；大文件用 offset 分段
- 不要为了"确认环境"反复调用 pwd；直接用绝对路径操作
```

---

## 附：`2000` 不是限制，是 `read` 的默认参数

排查中出现的 "2000" 来自 `read` 工具的 `limit` 描述：
> "Maximum number of lines to return. Defaults to 2000."

模型每次显式传 `limit:2000/1800/270`，看起来像"被 2000 限制"，实为**模型自选参数**。
若希望子 agent 不被误读，可在 prompt 里写明"limit 不传即默认"。

---

## 结论

| 问题 | 层级 | 修复 |
|---|---|---|
| bash 对已达标模式仍报 escalation 错 | **DSH 工具缺陷** | 忽略而非报错（方案 A） |
| 派发 prompt 未声明工具参数约定 | **我们的 prompt 缺陷** | 加固定约束段（方案 B） |
| "2000 限制"误读 | 描述歧义 | prompt 里说明 limit 语义 |

> 证据来源：`/www/dsh/home/sessions/--www-deepseek~0020harness~0020workspace--/1247c9dd-b000-46e9-a2e2-815d1149d2f9/session.jsonl.zstd`
> （解压后 177 事件 / 18 tool-call / 18 tool-result / 5 失败）
