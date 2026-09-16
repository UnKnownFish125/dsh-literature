#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_skill_routes.py — skill 管理体系的 HTTP 路由层。

由 literature_server.py 的 do_GET/do_POST/do_PATCH/do_DELETE 分发调用：
    if skill_routes.try_handle(self, method, parts, qs, body):
        return

设计约束（依据 docs/dsh-literature-skill-management-v02.md）：
- workspace_id 一律由调用方显式提供（按 #668 规则解析）；**本层不做任何兜底**。
- 权限语义沿用既有约定：写传 ws≠资源区 → 403；读传 ws≠区 → 404（不泄露）。
- 认证（Bearer）/ 拒 Origin 由 server.py 的 `_reject_browser_origin()` 统一处理，
  且 do_GET 中本模块的 hook **必须排在它之后**——否则读路由会同时绕过 401 与 403
  （2026-09-16 实测缺陷：hook 曾在鉴权前，任何本机可访问者都能读技能元数据）。
  回归测试见 tests/test_server_dispatch_order.py。

端点：
  POST   /v1/skills                          创建（默认 workspace 私有）
  GET    /v1/skills                          列表（workspace_id / scope / lifecycle 过滤）
  GET    /v1/skills/<id>                     详情
  PATCH  /v1/skills/<id>                     更新（乐观锁 row_version）
  DELETE /v1/skills/<id>                     软删
  POST   /v1/skills/<id>/versions            创建版本（不可变）
  GET    /v1/skills/<id>/versions            版本列表
  GET    /v1/skill-versions/<vid>            版本详情
  POST   /v1/skills/<id>/promote             私有 → 全局（需批准人）
  GET    /v1/skills/<id>/stats               使用统计
  POST   /v1/skill-deployments               部署
  GET    /v1/skill-deployments               部署列表
  POST   /v1/skill-deployments/<id>/verify   重新核验
  POST   /v1/skill-deployments/<id>/rollback 回滚
  POST   /v1/skill-deployments/<id>/retire   退役（物理移出发现根）
  POST   /v1/skill-events                    事件上报（幂等）
  POST   /v1/skill-evaluations               评价上报（三源分列）
  GET    /v1/skill-events                    事件列表
"""

import os
import sys

SKILL_HEADS = frozenset((
    "skills", "skill-versions", "skill-deployments", "skill-events", "skill-evaluations",
))


class _Unavailable(Exception):
    """对应模块尚未就位（部署/域逻辑仍在并行开发）。"""


def _db_path(handler):
    """从宿主 server 模块解析 DB 路径（不硬编码、不依赖 server 实例属性）。"""
    mod = sys.modules.get(type(handler).__module__)
    path = getattr(mod, "DB_PATH", None)
    if not path:
        raise _Unavailable("无法解析 literature DB 路径（宿主未暴露 DB_PATH）")
    return path


def _skill_store(handler):
    if getattr(handler, "_skill_store_cache", None) is None:
        try:
            from literature_skills import SkillStore
        except ImportError as exc:  # pragma: no cover - 依赖并行交付
            raise _Unavailable("literature_skills 模块未就位: %s" % exc) from None
        handler._skill_store_cache = SkillStore(_db_path(handler))
    return handler._skill_store_cache


def _event_store(handler):
    if getattr(handler, "_skill_event_cache", None) is None:
        try:
            from literature_skill_events import SkillEventStore
        except ImportError as exc:  # pragma: no cover
            raise _Unavailable("literature_skill_events 模块未就位: %s" % exc) from None
        handler._skill_event_cache = SkillEventStore(_db_path(handler))
    return handler._skill_event_cache


def _deployer(handler):
    if getattr(handler, "_skill_deployer_cache", None) is None:
        try:
            from literature_skill_deploy import SkillDeployer
        except ImportError as exc:  # pragma: no cover
            raise _Unavailable("literature_skill_deploy 模块未就位: %s" % exc) from None
        mod = sys.modules.get(type(handler).__module__)
        cfg = getattr(mod, "SKILL_DEPLOY_CONFIG", None)
        if not cfg:
            raise _Unavailable("未配置 skill 部署目标（server.SKILL_DEPLOY_CONFIG 为空）")
        handler._skill_deployer_cache = SkillDeployer(_db_path(handler), cfg)
    return handler._skill_deployer_cache


def _ws(body, qs, key="workspace_id"):
    """显式取 workspace_id；不做兜底（#668）。"""
    if isinstance(body, dict) and body.get(key):
        return str(body[key])
    values = qs.get(key) if qs else None
    if values:
        return str(values[0])
    return ""


def _vid(value):
    """路径参数转版本主键（int）。非法值交给域层抛 DomainError。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("version_id must be a positive integer") from None


def _body(handler):
    try:
        return handler._read_body() or {}
    except Exception:
        return {}


def _error_status(exc):
    name = type(exc).__name__
    if name in ("NotFoundError",):
        return 404
    if name in ("PermissionDenied", "ForbiddenError"):
        return 403
    if name in ("ConflictError",):
        return 409
    if name in ("ValidationError", "DomainError", "DeploymentError", "ValueError"):
        return 400
    return 500


def try_handle(handler, method, parts, qs, body=None):
    """分发 skill 相关请求。返回 True 表示已处理（已写出响应）。

    兼容两种前缀（均受支持）：
      /v1/skills、/v1/skill-events …              （契约文档写法，供日志注入插件使用）
      /v1/literature/skills、/v1/literature/...   （与既有 literature API 风格一致）
    """
    if len(parts) >= 3 and parts[0] == "v1" and parts[1] == "literature":
        if parts[2] in SKILL_HEADS:
            parts = [parts[0]] + parts[2:]      # 去掉 "literature"，保留 "v1"
    if len(parts) < 2 or parts[0] != "v1" or parts[1] not in SKILL_HEADS:
        return False
    head = parts[1]
    rest = parts[2:]
    try:
        return _dispatch(handler, method, head, rest, qs, body)
    except _Unavailable as exc:
        handler._send(503, {"error": str(exc)})
        return True
    except Exception as exc:  # noqa: BLE001 - 统一错误映射
        handler._send(_error_status(exc), {"error": str(exc), "kind": type(exc).__name__})
        return True


def _dispatch(handler, method, head, rest, qs, body):
    if head == "skills":
        return _skills(handler, method, rest, qs, body)
    if head == "skill-versions":
        return _versions(handler, method, rest, qs, body)
    if head == "skill-deployments":
        return _deployments(handler, method, rest, qs, body)
    if head == "skill-events":
        return _events(handler, method, rest, qs, body)
    if head == "skill-evaluations":
        return _evaluations(handler, method, rest, qs, body)
    return False


def _skills(handler, method, rest, qs, body):
    store = _skill_store(handler)
    if method == "POST" and not rest:
        payload = _body(handler)
        return handler._send(201, {"skill": store.create_skill(payload)})
    if method == "GET" and not rest:
        return handler._send(200, {"skills": store.list_skills(
            _ws(None, qs),
            scope=(qs.get("scope", [None])[0] or None),
            lifecycle=(qs.get("lifecycle", [None])[0] or None))})
    if not rest:
        return False
    skill_id = rest[0]
    if len(rest) == 1:
        if method == "GET":
            return handler._send(200, {"skill": store.get_skill(skill_id, _ws(None, qs))})
        if method == "PATCH":
            payload = _body(handler)
            return handler._send(200, {"skill": store.update_skill(
                skill_id, payload, workspace_id=_ws(payload, qs),
                row_version=payload.get("row_version"))})
        if method == "DELETE":
            payload = _body(handler)
            return handler._send(200, {"deleted": store.soft_delete_skill(
                skill_id, workspace_id=_ws(payload, qs),
                row_version=payload.get("row_version"),
                principal_id=str(payload.get("principal_id") or ""),
                request_id=str(payload.get("request_id") or ""))})
    if len(rest) == 2 and rest[1] == "versions":
        if method == "POST":
            payload = _body(handler)
            return handler._send(201, {"version": store.create_version(
                skill_id, payload, workspace_id=_ws(payload, qs))})
        if method == "GET":
            return handler._send(200, {"versions": store.list_versions(skill_id, _ws(None, qs))})
    if len(rest) == 2 and rest[1] == "promote" and method == "POST":
        payload = _body(handler)
        return handler._send(200, {"skill": store.promote_to_global(
            skill_id, approver=str(payload.get("approver") or ""),
            workspace_id=_ws(payload, qs), row_version=payload.get("row_version"))})
    if len(rest) == 2 and rest[1] == "stats" and method == "GET":
        return handler._send(200, {"stats": _event_store(handler).stats(
            skill_id, version_id=qs.get("version_id", [None])[0])})
    return False


def _blob_store(handler):
    """CAS 句柄（技能文件内容都在里面，blob_root 取自部署配置）。"""
    mod = sys.modules.get(type(handler).__module__)
    cfg = getattr(mod, "SKILL_DEPLOY_CONFIG", None) or {}
    root = cfg.get("blob_root")
    if not root:
        raise _Unavailable("未配置 blob_root（无法读取技能文件内容）")
    try:
        from literature_skill_blobs import BlobStore
    except ImportError as exc:  # pragma: no cover
        raise _Unavailable("literature_skill_blobs 未就位: %s" % exc) from None
    return BlobStore(root)


_PREVIEW_SUFFIXES = frozenset((
    ".md", ".txt", ".json", ".yaml", ".yml", ".js", ".mjs", ".cjs", ".ts", ".tsx",
    ".jsx", ".py", ".sh", ".css", ".html", ".htm", ".svg", ".xml", ".csv", ".toml",
    ".ini", ".cfg", ".sql", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".rb", ".php",
    ".lua", ".vue", ".svelte",
))
_PREVIEW_MAX_BYTES = 512 * 1024


def _previewable(rel_path, size_bytes=0):
    suffix = os.path.splitext(rel_path)[1].lower()
    if suffix and suffix not in _PREVIEW_SUFFIXES:
        return False
    return size_bytes <= _PREVIEW_MAX_BYTES


def _version_files(handler, version_id, want_path=""):
    """版本文件列表 / 单文件内容。SKILL.md 不在 skill_files 表里，单独补。"""
    rows = _query(handler,
                  "SELECT rel_path, size_bytes, sha256, mode FROM skill_files"
                  " WHERE skill_version_id=? ORDER BY rel_path", (version_id,))
    meta = _query(handler, "SELECT skill_md, length(skill_md) AS n FROM skill_versions WHERE id=?",
                  (version_id,))
    if not meta:
        return handler._send(404, {"error": "skill version not found"})
    entry_size = meta[0]["n"] or 0
    files = [{"rel_path": "SKILL.md", "size_bytes": entry_size, "sha256": "",
              "mode": 420, "entry": True,
              "previewable": _previewable("SKILL.md", entry_size)}]
    files += [{"rel_path": r["rel_path"], "size_bytes": r["size_bytes"], "sha256": r["sha256"],
               "mode": r["mode"], "entry": False,
               "previewable": _previewable(r["rel_path"], r["size_bytes"])} for r in rows]
    if not want_path:
        return handler._send(200, {"files": files, "count": len(files),
                                   "preview_max_bytes": _PREVIEW_MAX_BYTES})
    if want_path == "SKILL.md":
        return handler._send(200, {"path": "SKILL.md", "binary": False,
                                   "content": meta[0]["skill_md"], "size_bytes": entry_size})
    target = next((r for r in rows if r["rel_path"] == want_path), None)
    if target is None:
        return handler._send(404, {"error": "file not found in this version"})
    if not _previewable(target["rel_path"], target["size_bytes"]):
        return handler._send(200, {"path": target["rel_path"], "binary": True, "content": "",
                                   "size_bytes": target["size_bytes"],
                                   "reason": "二进制或超过预览上限（%d B）" % _PREVIEW_MAX_BYTES})
    data = _blob_store(handler).get(target["sha256"])
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return handler._send(200, {"path": target["rel_path"], "binary": True, "content": "",
                                   "size_bytes": target["size_bytes"], "reason": "非 UTF-8 文本"})
    return handler._send(200, {"path": target["rel_path"], "binary": False,
                               "content": text, "size_bytes": target["size_bytes"]})


def _versions(handler, method, rest, qs, body):
    if method == "GET" and len(rest) == 1:
        store = _skill_store(handler)
        return handler._send(200, {"version": store.get_version(_vid(rest[0]), _ws(None, qs))})
    if method == "GET" and len(rest) == 2 and rest[1] == "files":
        want = (qs.get("path") or [""])[0]
        return _version_files(handler, _vid(rest[0]), want)
    if method == "POST" and len(rest) == 2 and rest[1] == "review":
        payload = body if isinstance(body, dict) and body else _body(handler)
        store = _skill_store(handler)
        return handler._send(200, {"version": store.review_version(
            _vid(rest[0]), payload.get("decision"), str(payload.get("reviewer") or ""),
            workspace_id=_ws(payload, qs))})
    return False


def _query(handler, sql, params=()):
    """只读查询（部署器没有列表方法，直接查库）。"""
    import sqlite3
    conn = sqlite3.connect(_db_path(handler), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def _deployments(handler, method, rest, qs, body):
    dep = _deployer(handler)
    if method == "POST" and not rest:
        payload = _body(handler)
        return handler._send(201, {"deployment": dep.deploy(
            payload.get("skill_id"), payload.get("version_id"), payload.get("target_id"))})
    if method == "GET" and not rest:
        rows = _query(handler, "SELECT * FROM skill_deployments ORDER BY updated_at DESC LIMIT 200")
        return handler._send(200, {"deployments": rows})
    if len(rest) == 2 and method == "POST":
        action = rest[1]
        if action == "verify":
            return handler._send(200, {"deployment": dep.verify(rest[0])})
        if action == "rollback":
            return handler._send(200, {"deployment": dep.rollback(rest[0])})
        if action == "retire":
            row = _query(handler, "SELECT skill_id, target_id FROM skill_deployments WHERE id=?", (rest[0],))
            if not row:
                return handler._send(404, {"error": "deployment not found"})
            return handler._send(200, {"deployment": dep.retire(row[0]["skill_id"], row[0]["target_id"])})
    return False


def _events(handler, method, rest, qs, body):
    store = _event_store(handler)
    if method == "POST" and not rest:
        payload = _body(handler)
        return handler._send(201, store.record_event(payload))
    if method == "GET" and not rest:
        return handler._send(200, {"events": store.list_events(
            qs.get("skill_id", [None])[0],
            since=(float(qs["since"][0]) if qs.get("since") else None),
            k=int(qs.get("k", ["100"])[0]),
            workspace_id=_ws(None, qs),
            version_id=qs.get("version_id", [None])[0],
            event_kind=qs.get("event_kind", [None])[0])})
    return False


def _evaluations(handler, method, rest, qs, body):
    store = _event_store(handler)
    if method == "POST" and not rest:
        payload = _body(handler)
        return handler._send(201, store.record_evaluation(payload))
    if method == "GET" and not rest:
        return handler._send(200, {"evaluations": store.list_evaluations(
            qs.get("skill_id", [None])[0],
            version_id=qs.get("version_id", [None])[0],
            kind=qs.get("kind", [None])[0],
            k=int(qs.get("k", ["100"])[0]))})
    return False
