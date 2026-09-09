#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_skill_import.py — 把磁盘上的 SKILL.md 目录导入 literature（draft）。

用途：GitHub 素体（如 lieflat-charts）落盘后，一次性登记为私有 draft 技能，
由 UI 审核后发布。导入只写 draft，**不自动生效、不自动全局**。

流程：
  1. 读 SKILL.md，校验 frontmatter（name/description 必填，正文非空）
  2. 收集目录文件（排除 .git / node_modules / __pycache__ / 隐藏文件 / 超限文件）
  3. create_skill（已存在同 slug 则复用）→ create_version（bundle manifest + 双哈希）
  4. 可选生成 L0/L1 分层

依赖 literature_skills.SkillStore（域层，唯一写入口）。
"""
import argparse
import json
import os
import re
import sys

EXCLUDE_DIRS = frozenset((".git", "node_modules", "__pycache__", ".github",
                          ".vscode", ".idea", "dist", "build"))
EXCLUDE_FILES = frozenset((".DS_Store",))
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES = 256
MAX_TOTAL_BYTES = 50 * 1024 * 1024
TEXT_SUFFIXES = frozenset((
    ".md", ".txt", ".json", ".yaml", ".yml", ".js", ".mjs", ".cjs", ".ts", ".tsx",
    ".jsx", ".py", ".sh", ".css", ".html", ".htm", ".svg", ".xml", ".csv", ".toml",
    ".ini", ".cfg", ".env", ".gitignore", ".sql", ".go", ".rs", ".java", ".c", ".h",
    ".cpp", ".rb", ".php", ".lua", ".vue", ".svelte",
))

# ── GPU 依赖探测（面向"纯 CPU 服务器"场景）────────────────────────────────
# 只做标记、不阻断导入：命中即记入 compatibility，前端可红标提示。
_GPU_PATTERNS = (
    ("cuda", re.compile(r"\bcuda\b", re.I)),
    ("nvidia", re.compile(r"\bnvidia\b", re.I)),
    ("cupy", re.compile(r"\bcupy\b", re.I)),
    ("torch_cuda", re.compile(r"torch\.cuda|\.cuda\(\)|cuda:\d", re.I)),
    ("tensorrt", re.compile(r"\btensorrt\b", re.I)),
    ("opencl", re.compile(r"\bopencl\b", re.I)),
    ("rapids", re.compile(r"\brapids\b|\bcudf\b|\bcuml\b", re.I)),
    ("gpu_generic", re.compile(r"\bGPU\b")),
)


def scan_gpu_dependencies(skill_md, files=None):
    """扫描 SKILL.md 与文本附件中的 GPU 依赖线索。

    返回 {"gpu_required": bool, "hits": [{"path","marker"}], "scanned": n}。
    只扫可 UTF-8 解码的文本，二进制资源跳过。
    """
    hits, scanned = [], 0
    targets = [("SKILL.md", skill_md.encode("utf-8") if isinstance(skill_md, str) else skill_md)]
    for rel, data in (files or {}).items():
        suffix = os.path.splitext(rel)[1].lower()
        if suffix and suffix not in TEXT_SUFFIXES:
            continue
        targets.append((rel, data))
    for rel, data in targets:
        try:
            text = data.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            continue
        scanned += 1
        for marker, pattern in _GPU_PATTERNS:
            if pattern.search(text):
                hits.append({"path": rel, "marker": marker})
    return {"gpu_required": bool(hits), "hits": hits, "scanned": scanned}


class ImportError_(ValueError):
    pass


def _slug_from(name):
    import re
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return s or "unnamed-skill"


def collect_bundle(root, max_files=MAX_FILES, max_total=MAX_TOTAL_BYTES,
                   max_file=MAX_FILE_BYTES):
    """收集目录文件。返回 ({rel_path: bytes}, {"skipped": [...]})。

    跳过：排除目录、隐藏文件（.gitignore 之类保留）、超限文件；SKILL.md 单独返回。
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise ImportError_("not a directory: " + root)
    files, modes, skipped, total = {}, {}, [], 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            if name in EXCLUDE_FILES:
                continue
            if name.startswith(".") and name not in (".gitignore", ".env.example"):
                skipped.append((name, "hidden"))
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if os.path.islink(path):
                skipped.append((rel, "symlink"))
                continue
            size = os.path.getsize(path)
            if size > max_file:
                skipped.append((rel, "too-large %.1fMB" % (size / 1048576)))
                continue
            if rel == "SKILL.md":
                continue
            if len(files) + 1 > max_files:
                skipped.append((rel, "too-many-files"))
                continue
            if total + size > max_total:
                skipped.append((rel, "total-size-exceeded"))
                continue
            with open(path, "rb") as fh:
                files[rel] = fh.read()
            modes[rel] = os.stat(path).st_mode & 0o777
            total += size
    return files, modes, {"skipped": skipped, "bytes": total}


def import_directory(db_path, root, workspace_id, slug=None, title="",
                     source_kind="manual", source_url="", source_ref="",
                     generate_layers_for=True, created_by="importer"):
    """把目录导入为 workspace 私有 draft。返回结果字典。"""
    from literature_skills import SkillStore
    from literature_skill_layers import LayerStore

    root = os.path.abspath(root)
    skill_md_path = os.path.join(root, "SKILL.md")
    if not os.path.isfile(skill_md_path):
        raise ImportError_("SKILL.md not found in " + root)
    with open(skill_md_path, encoding="utf-8") as fh:
        skill_md = fh.read()

    checked = SkillStore.validate_skill_md(skill_md)
    fm = checked["frontmatter"]
    name = slug or _slug_from(fm.get("name") or os.path.basename(root))
    files, modes, meta = collect_bundle(root)
    gpu = scan_gpu_dependencies(skill_md, files)

    # 内容寻址落盘：skill_files 只存元数据，正文必须进 CAS 才能在无源目录的
    # 服务器上重建完整 bundle（否则部署只有 SKILL.md）。
    from literature_skill_blobs import BlobStore
    blobs = BlobStore(os.path.join(os.path.dirname(os.path.abspath(db_path)), "blobs"))
    blobs.put_files(files)

    store = SkillStore(db_path)
    try:
        skill = store.get_skill(name, workspace_id)
        created_skill = False
    except Exception:
        skill = store.create_skill({
            "slug": name, "workspace_id": workspace_id,
            "title": title or fm.get("name") or name,
            "description": (fm.get("description") or "")[:500],
            "created_by": created_by,
        })
        created_skill = True

    version = store.create_version(skill["id"], {
        "skill_md": skill_md, "workspace_id": workspace_id,
        "files": [{"rel_path": rel, "content": data, "mode": modes.get(rel, 0o644)}
                  for rel, data in files.items()],
        "source_kind": source_kind, "source_url": source_url,
        "source_ref": source_ref, "created_by": created_by,
        "compatibility": {
            "gpu_required": gpu["gpu_required"],
            "gpu_hits": gpu["hits"][:20],
            "cpu_only_ok": not gpu["gpu_required"],
            "blob_store": "cas-v1",
            "files": len(files),
        },
    })

    layers = None
    if generate_layers_for:
        try:
            layers = LayerStore(db_path).generate_for(version["id"])
        except Exception as exc:
            layers = {"ok": False, "error": str(exc)[:160]}

    return {
        "skill_id": skill["id"], "slug": name, "created_skill": created_skill,
        "version_id": version["id"], "version": version["version"],
        "created_version": version.get("created", True),
        "files": len(files), "bytes": meta["bytes"], "skipped": meta["skipped"],
        "warnings": checked["warnings"],
        "ignored_frontmatter_keys": checked["ignored_frontmatter_keys"],
        "gpu": gpu,
        "layers": layers,
    }


def _self_test():
    import json
    import tempfile
    with tempfile.TemporaryDirectory(prefix="skill-import-") as tmp:
        root = os.path.join(tmp, "src")
        os.makedirs(os.path.join(root, "templates"))
        os.makedirs(os.path.join(root, ".git"))
        os.makedirs(os.path.join(root, "node_modules"))
        with open(os.path.join(root, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nname: demo-import\ndescription: 导入自测\nversion: 9\n---\n"
                     "# 正文\n做一件事。\n")
        with open(os.path.join(root, "templates", "a.html"), "w", encoding="utf-8") as fh:
            fh.write("<html></html>")
        with open(os.path.join(root, "color.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
        with open(os.path.join(root, ".git", "config"), "w") as fh:
            fh.write("secret")
        with open(os.path.join(root, "node_modules", "x.js"), "w") as fh:
            fh.write("x")
        files, modes, meta = collect_bundle(root)
        assert set(files) == {"templates/a.html", "color.png"}, sorted(files)
        assert "SKILL.md" not in files
        assert not any(".git" in k or "node_modules" in k for k in files)
        print("PASS collect_bundle: 收集文本+二进制，排除 .git/node_modules，SKILL.md 单独处理")

        checked = __import__("literature_skills").SkillStore.validate_skill_md(
            open(os.path.join(root, "SKILL.md"), encoding="utf-8").read())
        assert checked["frontmatter"]["version"] == 9
        assert "version" in checked["ignored_frontmatter_keys"]
        print("PASS validate: frontmatter 全字段保留 + DSH 忽略字段识别")

        db = os.path.join(tmp, "t.db")
        from literature_skill_schema import ensure_skill_schema
        ensure_skill_schema(db)
        ws = "11111111-2222-3333-4444-555555555555"
        res = import_directory(db, root, ws, generate_layers_for=False)
        assert res["created_skill"] and res["files"] == 2, res
        assert res["slug"] == "demo-import"
        print(f"PASS import: skill={res['slug']} v{res['version']} files={res['files']} bytes={res['bytes']}")
        # 重复导入 → 同 slug 复用 skill，新版本（source_key 未设，故追加版本）
        res2 = import_directory(db, root, ws, generate_layers_for=False)
        assert res2["created_skill"] is False
        print("PASS idempotent-ish: 重复导入复用 skill、追加版本")
        print("ALL IMPORT SELF-TESTS PASSED")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--db", help="literature.db 路径")
    ap.add_argument("--root", help="含 SKILL.md 的目录")
    ap.add_argument("--workspace-id", help="目标工作区 UUID（必填，不做兜底）")
    ap.add_argument("--slug", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--source-url", default="")
    ap.add_argument("--source-ref", default="")
    ap.add_argument("--no-layers", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        _self_test()
    elif args.db and args.root and args.workspace_id:
        out = import_directory(args.db, args.root, args.workspace_id, slug=args.slug or None,
                               title=args.title, source_url=args.source_url,
                               source_ref=args.source_ref,
                               generate_layers_for=not args.no_layers)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        ap.print_help()
