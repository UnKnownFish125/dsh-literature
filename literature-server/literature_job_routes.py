#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长任务监控路由（阶段 4.2）。

端点：
  GET  /v1/literature/jobs                 任务列表（默认 50 条）
       ?active=true                        只看 running/stalled
       ?limit=N
  GET  /v1/literature/jobs/<id>            单任务详情
  POST /v1/literature/jobs                 新建任务  {kind,total,title,meta}
  POST /v1/literature/jobs/<id>/tick       更新进度  {done,total,meta}（done 省略=自增）
  POST /v1/literature/jobs/<id>/finish     结束任务  {error}（error 空=成功）
"""
import json
import time

import literature_jobs as J


def _body(body):
    if not body:
        return {}
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    except Exception:
        return {}


def try_handle(handler, method, parts, qs, body=None):
    if len(parts) < 3 or parts[0] != "v1" or parts[1] != "literature" or parts[2] != "jobs":
        return False
    try:
        # ---- 列表 / 新建
        if len(parts) == 3:
            if method == "GET":
                limit = int((qs.get("limit", ["50"])[0]) or 50)
                active = (qs.get("active", ["false"])[0] == "true")
                handler._send(200, {
                    "jobs": J.list_jobs(limit=limit, active_only=active),
                    "counts": J.counts(),
                    "now": time.time(),
                    "stale_after_sec": J.STALE_AFTER,
                })
                return True
            if method == "POST":
                p = _body(body)
                try:
                    total = int(p.get("total") or 0)
                except (TypeError, ValueError):
                    handler._send(400, {"error": "total must be an integer",
                                        "got": repr(p.get("total"))})
                    return True
                if total < 0:
                    handler._send(400, {"error": "total must be >= 0", "got": total})
                    return True
                kind = p.get("kind") or "task"
                if not isinstance(kind, str):
                    kind = "task"
                jid = J.start(kind=kind.strip()[:40] or "task",
                              total=total,
                              title=str(p.get("title") or "")[:120],
                              meta=p.get("meta") if isinstance(p.get("meta"), dict) else {})
                handler._send(201, {"id": jid})
                return True
            handler._send(405, {"error": "method not allowed"})
            return True

        jid = parts[3]
        # ---- 单任务
        if len(parts) == 4:
            if method != "GET":
                handler._send(405, {"error": "method not allowed"})
                return True
            for j in J.list_jobs(limit=500):
                if j["id"] == jid:
                    handler._send(200, {"job": j})
                    return True
            handler._send(404, {"error": "job not found", "id": jid})
            return True

        # ---- 子动作
        action = parts[4]
        if method != "POST":
            handler._send(405, {"error": "method not allowed"})
            return True
        p = _body(body)
        if not any(j["id"] == jid for j in J.list_jobs(limit=500)):
            handler._send(404, {"error": "job not found", "id": jid})
            return True
        if action == "tick":
            done = p.get("done")
            try:
                done = None if done is None else int(done)
                total = p.get("total")
                total = None if total is None else int(total)
            except (TypeError, ValueError):
                handler._send(400, {"error": "done/total must be integers"})
                return True
            r = J.tick(jid, done=done, total=total,
                       meta=p.get("meta") if isinstance(p.get("meta"), dict) else None)
            handler._send(200, {"id": jid, "done": r})
            return True
        if action == "finish":
            J.finish(jid, error=p.get("error") or "")
            handler._send(200, {"id": jid, "ok": True})
            return True
        if action == "cancel":
            J.cancel(jid)
            handler._send(200, {"id": jid, "ok": True})
            return True
        handler._send(404, {"error": "unknown action", "action": action})
        return True
    except Exception as exc:
        handler._send(500, {"error": str(exc), "kind": type(exc).__name__})
        return True
