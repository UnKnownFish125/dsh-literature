#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature kb-server — dsh-literature 知识库查询服务（面向 agent 的查询代理）

架构：DSH Agent →(lit-api)→ 本服务 →(只读 Bearer)→ deepmemory memory-server
定位：纯查询代理，不持有知识副本；不改 deepmemory 本体（H2 分工：CLI kb-query.py 归 deepmemory 仓库，
      本服务是 DSH agent 工具层的 HTTP 守护 + kb_* 工具注册）。

安全（H4）：绑定 127.0.0.1（回环），公网不可达。
端口（H3）：生产 6262 / 测试 6261（6260 已被 dsh-literature 占用）。
上游（M3）：LITERATURE_MEMORY_URL env 指定（生产 6230 / 测试 6240），unit 显式配置。
"""

import json
import os
import secrets
import sqlite3
import time
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
API_TOKEN_FILE = os.environ.get("LITERATURE_API_TOKEN_FILE", os.path.join(DATA_DIR, "api-token"))
PORT = int(os.environ.get("LITERATURE_SERVER_PORT", "6262"))
# 上游 deepmemory：测试 6240 / 生产 6230（M3：env 显式配置，防测试流量打生产库）
MEMORY_URL = os.environ.get("LITERATURE_MEMORY_URL", "http://127.0.0.1:6230")
MEMORY_TOKEN_FILE = os.environ.get("LITERATURE_MEMORY_API_TOKEN_FILE",
                                   os.path.join(DATA_DIR, "memory-api-token"))
TIMEOUT = float(os.environ.get("LITERATURE_UPSTREAM_TIMEOUT", "10"))
# 默认 workspace：deepmemory 记忆按 workspace 硬过滤，必须显式传 workspace_id 才能召回
DEFAULT_WORKSPACE = os.environ.get("LITERATURE_DEFAULT_WORKSPACE", "deepseek-harness")

os.makedirs(DATA_DIR, exist_ok=True)


def _ensure_token():
    if not os.path.exists(API_TOKEN_FILE):
        with open(API_TOKEN_FILE, "w", encoding="utf-8") as fh:
            fh.write(secrets.token_urlsafe(32))


def _read_memory_token():
    """上游 deepmemory token（只读通道；M1：该 token 是全权 token，沦陷即写权限——单机回环下可接受）。"""
    for path in (MEMORY_TOKEN_FILE,
                 os.path.join(os.path.dirname(BASE_DIR), "data", "api-token"),
                 "/www/dsh/home/.dsh-memory-api-token"):
        if not path:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                token = fh.read().strip()
            if token:
                return token
        except OSError:
            continue
    return ""


def upstream(method, path, body=None):
    """只读调用 deepmemory。返回 (status, json)。"""
    token = _read_memory_token()
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(MEMORY_URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, json.JSONDecodeError):
            return exc.code, {"error": f"upstream HTTP {exc.code}"}
    except Exception as exc:  # 网络/超时 → 503
        return 503, {"error": f"upstream unreachable: {exc}"}


def list_memories(workspace_id):
    """枚举某 workspace 全部 active 记忆（list 端点，不走语义召回）。"""
    st, data = upstream("GET", f"/v1/memories/list?workspace_id={urllib.parse.quote(workspace_id)}&status=active&limit=1000")
    if st != 200:
        return st, []
    return st, data.get("memories", [])


class Handler(BaseHTTPRequestHandler):
    server_version = "literature-kb/3.1"

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject(self):
        if self.headers.get("Origin"):
            self._send(403, {"error": "browser origin is not allowed"})
            return True
        try:
            with open(API_TOKEN_FILE, encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError:
            token = ""
        if token and self.headers.get("Authorization") != "Bearer " + token:
            self._send(401, {"error": "bearer token required"})
            return True
        return False

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return {}
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self._reject():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/")]

        if path == "/v1/literature/health":
            st, up = upstream("GET", "/v1/health")
            return self._send(200, {"status": "ok", "upstream": MEMORY_URL,
                                    "upstream_status": "ok" if st == 200 else f"degraded({st})"})
        # kb/browse?library=&workspace_id=
        if len(parts) == 4 and parts[:3] == ["v1", "literature", "kb"] and parts[3] == "browse":
            st, data = upstream("GET", "/v1/memories/libraries")
            if st != 200:
                return self._send(st if st != 503 else 503, data)
            libs = data.get("libraries", {})
            library = qs.get("library", [""])[0]
            if library and library in libs:
                libs = {library: libs[library]}
            return self._send(200, {"libraries": libs})
        # kb/constraints → bias 库全量枚举（list 端点，避免语义召回不全）
        if len(parts) == 4 and parts[:3] == ["v1", "literature", "kb"] and parts[3] == "constraints":
            ws = qs.get("workspace_id", [DEFAULT_WORKSPACE])[0]
            k = int(qs.get("k", ["50"])[0])
            st, mems = list_memories(ws)
            if st != 200:
                return self._send(503 if st == 503 else st, {"error": "upstream list failed"})
            bias = [m for m in mems if m.get("library") == "bias"]
            # 按 importance 降序
            bias.sort(key=lambda m: float(m.get("importance") or 0), reverse=True)
            return self._send(200, {"constraints": bias[:k], "count": len(bias),
                                    "note": "" if bias else "bias 库为空（需存量归类，见方案 S5）"})
        # kb/contracts → core 库枚举 + topic 过滤
        if len(parts) == 4 and parts[:3] == ["v1", "literature", "kb"] and parts[3] == "contracts":
            topic = qs.get("topic", [""])[0]
            ws = qs.get("workspace_id", [DEFAULT_WORKSPACE])[0]
            k = int(qs.get("k", ["20"])[0])
            st, mems = list_memories(ws)
            if st != 200:
                return self._send(503 if st == 503 else st, {"error": "upstream list failed"})
            core = [m for m in mems if m.get("library") == "core"]
            if topic:
                core = [m for m in core if topic in (m.get("content") or "")]
            core.sort(key=lambda m: float(m.get("importance") or 0), reverse=True)
            return self._send(200, {"contracts": core[:k], "count": len(core)})
        # kb/graph
        if len(parts) == 4 and parts[:3] == ["v1", "literature", "kb"] and parts[3] == "graph":
            st, data = upstream("GET", "/v1/graph/memories")
            if st != 200:
                return self._send(503 if st == 503 else st, data)
            return self._send(200, {"graph": data})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if self._reject():
            return
        parsed = urllib.parse.urlparse(self.path)
        parts = [urllib.parse.unquote(p) for p in parsed.path.strip("/").split("/")]
        body = self._body()
        # kb/query + kb/recall → deepmemory search（透传 library，Q2：分库已上线直接透传）
        if len(parts) == 4 and parts[:3] == ["v1", "literature", "kb"] and parts[3] in ("query", "recall"):
            query = str(body.get("query") or "").strip()
            if not query:
                return self._send(400, {"error": "query is required"})
            payload = {
                "query": query,
                "k": int(body.get("k") or 5),
                "include_archived": bool(body.get("include_archived")),
            }
            if body.get("library"):
                payload["library"] = body["library"]
            if body.get("workspace_id"):
                payload["workspace_id"] = body["workspace_id"]
            st, data = upstream("POST", "/v1/memories/search", payload)
            if st != 200:
                return self._send(503 if st == 503 else st, data)
            results = data.get("results", [])
            # recall 保留完整元数据；query 精简
            if parts[3] == "query":
                results = [{"id": r.get("id"), "content": r.get("content"),
                            "type": r.get("type"), "scope": r.get("scope"),
                            "library": r.get("library"), "importance": r.get("importance"),
                            "score": r.get("final_score")} for r in results]
            return self._send(200, {"query": query, "count": len(results), "results": results})
        return self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass  # 静默访问日志（systemd journal 已足）


def main():
    _ensure_token()
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)  # H4: 回环绑定
    print(f"literature kb-server listening on 127.0.0.1:{PORT} (upstream={MEMORY_URL})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
