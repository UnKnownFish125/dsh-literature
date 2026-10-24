#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""literature_skill_search_routes.py — 技能检索路由。

路径设计（避开既有 /skills/<id> 的通配，防止 id="search" 撞车）：
  人（关键词，确定性）：
    GET  /v1/literature/skill-search?q=&tag=&category=&lifecycle=&limit=
    GET  /v1/literature/skill-search/l0?name=            单条 L0（列表预览用）
    POST /v1/literature/skill-search/rebuild             重建 FTS + 嵌入
    GET  /v1/literature/skill-search/health              索引健康度（待嵌/失败数量）

  agent（语义，按需拉，默认零注入）：
    POST /v1/literature/skill-agent/search   {query, k, tag}
    POST /v1/literature/skill-agent/load     {name, layer}

agent 两个端点只返回 visibility='model' 且 lifecycle='active' 的技能；
k 服务端夹断到 8；search 永不返回正文，load 默认只给 L1。
"""
import json
import sqlite3

import literature_skill_search as S


def _db(handler):
    import sys
    mod = sys.modules.get(type(handler).__module__)
    path = getattr(mod, "DB_PATH", None)
    if not path:
        raise RuntimeError("无法解析 literature DB 路径")
    return path


def _connect(handler):
    c = sqlite3.connect(_db(handler), timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _body(body):
    if not body:
        return {}
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    except Exception:
        return {}


def _need_schema(c, handler):
    """skill 检索表不存在时给明确 503，而不是 500 堆栈。"""
    try:
        c.execute("SELECT 1 FROM skill_search_fts LIMIT 1")
        c.execute("SELECT 1 FROM skill_vectors LIMIT 1")
        return True
    except sqlite3.OperationalError:
        handler._send(503, {
            "error": "skill 检索索引未安装",
            "hint": "运行 python3 literature_skill_schema.py <db> 应用迁移 3",
        })
        return False


def try_handle(handler, method, parts, qs, body=None):
    if len(parts) < 3 or parts[0] != "v1" or parts[1] != "literature":
        return False
    head = parts[2]
    if head not in ("skill-search", "skill-agent"):
        return False

    c = None
    try:
        c = _connect(handler)

        # ------------------------------------------------ 人：关键词
        if head == "skill-search":
            if not _need_schema(c, handler):
                return True

            if method == "GET" and len(parts) == 3:
                q = (qs.get("q", [""])[0] or "").strip()
                rows = S.keyword_search(
                    c, q,
                    tag=(qs.get("tag", [""])[0] or None),
                    category=(qs.get("category", [""])[0] or None),
                    lifecycle=(qs.get("lifecycle", [""])[0] or None),
                    workspace_id=(qs.get("workspace_id", [""])[0] or None),
                    include_user_only=True,
                    limit=int((qs.get("limit", ["50"])[0] or 50)))
                handler._send(200, {"query": q, "count": len(rows), "skills": rows})
                return True

            if method == "GET" and len(parts) == 4 and parts[3] == "l0":
                name = (qs.get("name", [""])[0] or "").strip()
                r = c.execute("""
                    SELECT v.summary_l0 FROM skills s
                      JOIN skill_versions v ON v.id = COALESCE(s.active_version_id,
                        (SELECT id FROM skill_versions x WHERE x.skill_id=s.id ORDER BY x.version DESC LIMIT 1))
                     WHERE s.deleted_at IS NULL AND (s.slug=? OR s.title=?) LIMIT 1""", (name, name)).fetchone()
                handler._send(200, {"name": name, "l0": (r[0] if r else "") or ""})
                return True

            if method == "GET" and len(parts) == 4 and parts[3] == "health":
                def count(sql):
                    try:
                        return c.execute(sql).fetchone()[0]
                    except sqlite3.OperationalError:
                        return -1
                handler._send(200, {
                    "fts_rows": count("SELECT COUNT(*) FROM skill_search_fts"),
                    "versions_total": count("SELECT COUNT(*) FROM skill_versions"),
                    "vectors_ok": count("SELECT COUNT(*) FROM skill_vectors WHERE status='ok'"),
                    "vectors_pending": count("SELECT COUNT(*) FROM skill_vectors WHERE status IN ('pending','stale')"),
                    "vectors_failed": count("SELECT COUNT(*) FROM skill_vectors WHERE status='failed'"),
                    "model_visible": count(
                        "SELECT COUNT(*) FROM skills WHERE deleted_at IS NULL"
                        " AND visibility='model' AND lifecycle='active'"),
                })
                return True

            if method == "POST" and len(parts) == 4 and parts[3] == "rebuild":
                p = _body(body)
                out = {"fts": S.rebuild_all(c)}
                c.commit()
                if p.get("embed", True):
                    out["embed"] = S.embed_pending(c, limit=int(p.get("embed_limit") or 200))
                handler._send(200, out)
                return True

            handler._send(405 if method not in ("GET", "POST") else 404,
                          {"error": "not found", "path": "/".join(parts)})
            return True

        # ------------------------------------------------ agent：语义
        if method != "POST":
            handler._send(405, {"error": "method not allowed (agent endpoints are POST only)"})
            return True
        if not _need_schema(c, handler):
            return True

        if len(parts) == 4 and parts[3] == "search":
            p = _body(body)
            r = S.semantic_search(c, p.get("query") or "", k=p.get("k") or S.DEFAULT_K,
                                  tag=p.get("tag"))
            # 只回 name/l0/score —— 绝不回正文（防全注入的闸）
            handler._send(200, {
                "results": [{"name": x["name"], "l0": x["l0"], "score": x["score"]}
                            for x in (r.get("results") or [])],
                "k": r.get("k", S.DEFAULT_K),
                "note": r.get("reason") or ("命中 %d 条；需要正文再用 literature_skill_load"
                                            % len(r.get("results") or [])),
            })
            return True

        if len(parts) == 4 and parts[3] == "load":
            p = _body(body)
            layer = (p.get("layer") or "l1").lower()
            r = S.load_skill(c, p.get("name") or "", layer=layer,
                             workspace_id=p.get("workspace_id"))
            if not r.get("ok"):
                handler._send(404, r)
                return True
            handler._send(200, r)
            return True

        handler._send(404, {"error": "not found"})
        return True
    except Exception as exc:
        try:
            handler._send(500, {"error": str(exc), "kind": type(exc).__name__})
        except Exception:
            pass
        return True
    finally:
        if c is not None:
            c.close()
