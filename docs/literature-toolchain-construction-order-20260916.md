# 文献工具链施工单（报告 + astra 评审合并版）

> 来源：`/data1/论文/文献工具链修复交接报告.md`（只读审计）
> 评审：astra（gpt-6-astra，独立验证 + 挑战，2026-09-16）
> 状态：**待用户拍板**，未动任何代码
> 原则：每条改动标明来源【报告】/【astra 修正】，便于追溯与追责

---

## 0. 一句话

报告诊断**大体可信**，但**不能照抄 §3 实施**——astra 实测发现 §3.1 有确定路径 bug、§3.4 有安全 bug，且 Q1 的方案 B 会破坏隔离语义。

---

## 1. 已确认成立（报告诊断准确）

| # | 结论 | 双方一致 |
|---|---|---|
| 1 | kb 插件用相对 URL（`/lit-api/v1/literature`），Node fetch 不可用 | ✅ |
| 2 | literature 插件未挂载（preset 零引用） | ✅ |
| 3 | `DEFAULT_WS = 'deepseek-hardness'` 幽灵值 + `UP.DEFAULT_WORKSPACE='deepseek-harness'` | ✅ |
| 4 | `literature_attach` 空桩、插件缺 `export const inject = ['tools']` | ✅ |
| 5 | 6260 服务端健康（kb/browse、constraints、query、knowledge-count=121 全 200） | ✅ |
| 6 | `search_knowledge:985-987` 硬 workspace 过滤 | ✅ |
| 7 | **skill 读路由未鉴权、未拒 Origin**（实测无 Bearer 200、带 Origin 仍 200） | ✅ |

---

## 2. astra 修正（报告有误，**必须改**）

### 2.1 §3.1 API 基址漏后缀 → 会全 404 【astra】

```js
// 报告写的（错）
const API = 'http://127.0.0.1:' + String(process.env.LITERATURE_SERVER_PORT || '6260')
// 调用 api('/kb/query') → http://127.0.0.1:6260/kb/query  ❌ 404

// 正确
const API = 'http://127.0.0.1:' + String(port) + '/v1/literature'
```

### 2.2 §3.4 `TOKEN_FILES` 跨环境 fallback 不安全 【astra】

报告给的兜底列表**先列生产 token 再列测试**，实测后果：

```
dsh-test 插件读取顺序（我已逐步核实）：
  1. env LITERATURE_API_TOKEN_FILE        → 未设，跳过
  2. /www/dsh-test-home/.dsh-...-token    → 缺失，跳过
  3. /root/.dsh-literature-api-token      → 缺失，跳过
  4. /www/dsh-literature-deploy/.../api-token → ⚠️ 生产 token 命中
  且 LITERATURE_SERVER_PORT 未设 → 默认 6260 = 生产库
  ⇒ 测试实例用生产 token 读写生产库
```

**正确做法**：**删除跨环境 fallback**，按 unit 显式注入：
```ini
# dsh-test.service
Environment=LITERATURE_SERVER_PORT=6263
Environment=LITERATURE_API_TOKEN_FILE=/www/dsh-test-literature-server/data/api-token
```
**并加启动自检**：token 文件路径与端口必须与 unit 一致，否则拒绝启动/明确报错。

### 2.3 P0-1 不是"低风险" 【astra】

修 URL 会**同时激活 7 个工具**（插件实际定义 7 个，非报告说的 6 个），**其中含写工具** `kb_archive_library`。
⇒ 不能笼统称"低风险，不动服务端"。

### 2.4 Q1 的 B 方案不是"复用 bias" 【astra，推翻我的判断】

```python
# list_knowledge:800      ← 有 bias 例外
if workspace_id and library != "bias":

# search_knowledge:985    ← 无 bias 例外（我核对全文确认）
if workspace_id:
    sql += " AND workspace_id=?"
```
⇒ 给 shared 加豁免 = **新造跨区语义**，不是复用既有裁决。

---

## 3. astra 补出的遗漏（报告与我均未发现）

| # | 遗漏 | 后果 |
|---|---|---|
| 3.1 | `kb_archive_library` 写操作**未传 workspace_id** | 修 URL 后必 **400**（domain:790-791 守卫），工具仍不可用 |
| 3.2 | `kb_constraints` / `kb_contracts` 默认走 `UP.DEFAULT_WORKSPACE='deepseek-harness'`，**且工具签名无法传 ws** | **修好 URL 后仍然失明**——这是"121 条查不到"的另一半根因 |
| 3.3 | `kb_graph` 同样不传 ws | 上游行为待确认 |
| 3.4 | literature 插件 `DEFAULT_WS` 改空 **≠ 修好** | 调用方不显式传时会**写空 workspace**，从"写错库"变成"写空库" |

**⇒ 关键推论**：3.2 说明 **P0-1 不是"改个 URL 就完事"**，工具签名本身要改。

---

## 4. astra 的方案建议

### Q1 跨工作区供给 → **第四种方案**

| 方案 | 裁定 |
|---|---|
| A 显式传 workspace_id | **短期采用**（恢复隔离与可用性，需各工作区约定） |
| B shared 跳过过滤 | **禁止**（破坏现有隔离语义） |
| C 写进 bias | **绝不可用**（bias 是行为约束且服务端保护） |
| **D 显式"发布/共享"表 + 只读投影 + ACL** | ✅ **长期正解** |

### Q2 顺序

```
1. 服务端/插件契约与【测试隔离】   ← 防打生产库
2. kb 插件 URL + 工具签名（约束/契约要能传 ws）
3. literature 工具实现与挂载
4. 最后才做共享设计
```
> **不要先激活带写操作的半成品**

### Q3 附带项
- **附带-1（skill 鉴权）：安全最高优先，必修 + 回归测试**
- 附带-2（`kb_query` 描述 / 幻影默认值）：必修
- 附带-3（退役 unit、`/health`）：低风险清理，`/health` 另立不阻塞

### Q4 工作区脚手架
建，但**在工具/归属语义定稿后**再建；`AGENTS.md` 要写明 workspace UUID、写入前显式 ws、论文共享发布流程

---

## 5. astra 的"只能做一件事"

> **优先：修 skill GET 鉴权绕过 + 回归测试**（当前任何本机可访问者可读技能元数据）
> 若以业务恢复优先：**先锁死测试实例的端口与 token 隔离**，防止后续验证打生产库

**我的建议：两件一起做**，因为都低风险、独立、且互不依赖：

| 步骤 | 动作 | 风险 |
|---|---|---|
| 0-a | `literature_server.py` 把 `SKILL_ROUTES.try_handle` 移到 `_reject_browser_origin()` **之后** + 回归测试 | 低（只挪 4 行） |
| 0-b | `dsh-test.service` 显式注入 `LITERATURE_SERVER_PORT=6263` + `LITERATURE_API_TOKEN_FILE` | 低（改 unit + reload） |

**都不需要重启 dsh-web**（0-a 重启 6260；0-b 只 reload dsh-test）。

---

## 6. 待用户裁定

- [ ] **是否按第 5 节开工**（0-a + 0-b）
- [ ] Q1 长期方案 D（发布/共享表 + 只读投影 + ACL）是否立项
- [ ] Q2 后续顺序是否照 astra 建议
- [ ] Q4 脚手架是否现在就建（还是等语义定稿）

---

## 7. 附：本次评审的证据留档

```
# skill 鉴权绕过（实测）
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:6260/v1/skill-deployments
→ 200（无 Authorization）
curl -s -o /dev/null -w '%{http_code}' -H 'Origin: http://evil.example' \
  "http://127.0.0.1:6260/v1/skills?workspace_id=x"  → 400（路由执行了，未被 403 拦）
# 对照
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:6260/v1/literature/kb/browse → 401

# 代码位置
literature_server.py:290   SKILL_ROUTES.try_handle(...)      ← 鉴权之前
literature_server.py:295   self._reject_browser_origin()     ← 鉴权在此

# 域层守卫（archive 不会全库误归档）
literature_domain.py:790-791  if not workspace_id: raise DomainError
```
