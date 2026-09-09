# skill bundle 哈希与 manifest 约定（v1）

> 用途：`literature_skills.py`（导入/版本）与 `literature_skill_deploy.py`（部署/对账）必须使用**完全一致**的算法，否则对账必然失败。
> 状态：**冻结**（任何修改须同时通知两个模块并升版本号）。

## 1. 术语

| 名称 | 含义 |
|---|---|
| `skill_md` | `SKILL.md` 文件的**原始字节内容**（含 frontmatter，不做任何换行/编码归一化） |
| `frontmatter_json` | 解析出的 frontmatter 全字段（保真，含 DSH 不认的键） |
| `files` | bundle 内除 `SKILL.md` 之外的所有普通文件（不含目录、不含符号链接） |
| `content_sha256` | `SKILL.md` 的哈希 |
| `artifact_sha256` | **整包**哈希（含 SKILL.md 与全部 files） |
| `manifest_json` | 整包清单（可复现 artifact_sha256） |

## 2. 计算算法（必须逐字节一致）

### 2.1 `content_sha256`
```
content_sha256 = sha256(skill_md_bytes).hexdigest()          # 小写 hex，64 字符
```

### 2.2 单文件哈希
```
file_sha256 = sha256(file_bytes).hexdigest()                 # 小写 hex
```

### 2.3 `manifest_json` 结构
```json
{
  "schema": 1,
  "slug": "<skill slug>",
  "version": <int>,
  "files": [
    {"rel_path": "scripts/plot.py", "size_bytes": 1234, "sha256": "…", "mode": 420, "is_symlink": 0}
  ],
  "entry": "SKILL.md",
  "bundle_sha256": "<artifact_sha256>"
}
```

### 2.4 `artifact_sha256`（整包）
**排序规则**：所有条目（含 `SKILL.md` 自身）按 `rel_path` 的 **UTF-8 字节序升序**排列。

**拼接口径**（每项一行，字段用 `\0` 分隔、行尾 `\n`）：
```
line = rel_path + "\0" + sha256 + "\0" + str(size_bytes) + "\n"
artifact_sha256 = sha256( "".join(lines).encode("utf-8") ).hexdigest()
```

- `SKILL.md` 的条目为 `rel_path="SKILL.md"`、`sha256=content_sha256`、`size_bytes=len(skill_md_bytes)`
- **不含**目录、**不含**符号链接（遇到即拒绝导入，不进哈希）
- `mode` 与 `is_symlink` **不参与** artifact 哈希（只进 manifest 供审计）

### 2.5 参考实现（可直接复制）
```python
import hashlib

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def bundle_sha256(skill_md: bytes, files: dict) -> str:
    """files: {rel_path: bytes}，不含 SKILL.md。

    口径与 §2.4 完全一致：**所有条目（含 SKILL.md 自身）统一按 rel_path
    的 UTF-8 字节序排序**，SKILL.md 不享有"固定第一"的特权。
    """
    entries = dict(files)
    entries["SKILL.md"] = skill_md
    h = hashlib.sha256()
    for rel_path in sorted(entries, key=lambda p: p.encode("utf-8")):
        data = entries[rel_path]
        h.update(rel_path.encode("utf-8")); h.update(b"\0")
        h.update(sha256_hex(data).encode("utf-8")); h.update(b"\0")
        h.update(str(len(data)).encode("utf-8")); h.update(b"\n")
    return h.hexdigest()
```

> 修正记录（2026-09-09，由部署器实现者发现）：初版参考实现把 `SKILL.md` 固定为第一条、
> 其余资源再排序，与 §2.4 的"全量排序"不一致（例如同时存在 `A.txt` 与 `README.md` 时
> 会产生不同哈希）。**现已统一为全量排序**，`SKILL.md` 参与排序。两模块必须使用本版实现。

## 3. 落库字段对应

| 字段 | 取值 |
|---|---|
| `skill_versions.skill_md` | `skill_md` 原文（str，UTF-8） |
| `skill_versions.content_sha256` | §2.1 |
| `skill_versions.artifact_sha256` | §2.4 |
| `skill_versions.manifest_json` | §2.3 的 JSON 字符串 |
| `skill_files.rel_path` / `sha256` / `size_bytes` / `mode` / `is_symlink` | 逐文件（**不含** SKILL.md 自身） |
| `skill_deployments.expected_current_hash` / `observed_hash` | **`artifact_sha256`** |

## 4. 部署对账口径

1. 部署前：`expected_current_hash = 目标版本 artifact_sha256`
2. 部署后：重新读取目标目录 → 按 §2.4 重算 → `observed_hash`
3. `observed_hash == expected_current_hash` → `state='verified'`
4. 不等 → `state='drift'`（**不得**改写 applied_version_id）
5. 目标目录缺少文件 / 多出文件 → 同样判 `drift`

## 5. 边界与拒绝条件

| 情况 | 处理 |
|---|---|
| 文件是符号链接 | **拒绝导入**（防越界） |
| `rel_path` 含 `..` 或为绝对路径 | 拒绝 |
| `SKILL.md` 不存在 | 拒绝 |
| 正文（frontmatter 之后）trim 后为空 | **拒绝**（DSH 接受空正文，我们更严） |
| frontmatter 缺 `name` 或 `description` | 拒绝（DSH 会静默忽略整文件） |
| 文件名含非 UTF-8 字节 | 拒绝 |
