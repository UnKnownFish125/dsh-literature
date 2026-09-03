#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_server.py — dsh-literature HTTP 服务（默认 6260，/lit-api 前缀给 web 插件代理）
契约 contract-v0.2 §4.2/§4.3：鉴权沿用 deepmemory（api-token + Bearer + 拒 Origin + 根 404）；
附件取回用 HMAC 短期签名 token（attachment-signing-key）。
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import literature_upstream as UP  # 单服务合并：deepmemory 上游（search/libraries/list/graph）

from literature_domain import (
    ConflictError,
    DomainError,
    LiteratumStore,
    NotFoundError,
    PermissionDenied,
    install_schema,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ATTACHMENT_DIR = os.path.join(DATA_DIR, "attachments")
DB_PATH = os.path.join(DATA_DIR, "literature.db")
API_TOKEN_FILE = os.environ.get("LITERATURE_API_TOKEN_FILE", os.path.join(DATA_DIR, "api-token"))
SIGNING_KEY_FILE = os.path.join(DATA_DIR, "attachment-signing-key")
PORT = int(os.environ.get("LITERATURE_SERVER_PORT", "6260"))
MAX_BODY_BYTES = int(os.environ.get("LITERATURE_MAX_BODY_BYTES", str(50 * 1024 * 1024)))
ATTACHMENT_TTL_SECONDS = 300  # 5 分钟

# 插件配置页（设置 → 插件 → 插件配置）schema：与 config_schema.json 同构
CONFIG_SCHEMA = {
    "basic": {
        "description": "基础",
        "type": "object",
        "items": {
            "server_url": {
                "description": "literature 服务地址",
                "hint": "Host 代理已固定 /lit-api，此项仅展示",
                "type": "string",
                "default": f"http://127.0.0.1:{PORT}",
                "readonly": True,
            },
            "default_workspace": {
                "description": "默认工作区",
                "hint": "未显式传 workspace_id 时使用的默认值",
                "type": "string",
                "default": "deepseek-hardness",
            },
        },
    },
    "attachment": {
        "description": "附件",
        "type": "object",
        "items": {
            "ttl_seconds": {
                "description": "取回签名有效期（秒）",
                "hint": "附件 URL 短期 token 的有效期，默认 300（5 分钟）",
                "type": "number",
                "default": 300,
            },
            "max_body_bytes": {
                "description": "上传大小上限（字节）",
                "type": "number",
                "default": MAX_BODY_BYTES,
            },
        },
    },
    "search": {
        "description": "检索",
        "type": "object",
        "items": {
            "default_k": {
                "description": "默认返回条数",
                "type": "number",
                "default": 5,
            },
        },
    },
}

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ATTACHMENT_DIR, exist_ok=True)

_store = None
_store_lock = threading.Lock()


def get_store():
    global _store
    with _store_lock:
        if _store is None:
            _store = LiteratumStore(DB_PATH)
    return _store


def _ensure_token_files():
    if not os.path.exists(API_TOKEN_FILE):
        with open(API_TOKEN_FILE, "w", encoding="utf-8") as fh:
            fh.write(secrets.token_urlsafe(32))
    if not os.path.exists(SIGNING_KEY_FILE):
        with open(SIGNING_KEY_FILE, "w", encoding="utf-8") as fh:
            fh.write(secrets.token_urlsafe(32))


def init_db():
    _ensure_token_files()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        install_schema(conn)
        conn.commit()
    finally:
        conn.close()


def _read_token(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _sign_attachment(file_path, expires):
    key = _read_token(SIGNING_KEY_FILE)
    message = f"{file_path}.{expires}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _verify_attachment(file_path, token, now=None):
    now = now if now is not None else time.time()
    if ".." in file_path or file_path.startswith("/") or "\\" in file_path:
        return False
    try:
        expires_epoch, sig = token.split(".")
        expires_epoch = int(expires_epoch)
    except (ValueError, AttributeError):
        return False
    if expires_epoch < now - 30 or expires_epoch > now + ATTACHMENT_TTL_SECONDS * 2:
        return False
    expected = _sign_attachment(file_path, expires_epoch)
    return hmac.compare_digest(expected, sig)


class Handler(BaseHTTPRequestHandler):
    server_version = "literature/0.2"

    # ---------------------------------------------------------------- helpers

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def _reject_browser_origin(self):
        if self.headers.get("Origin"):
            self._send(403, {"error": "browser origin is not allowed"})
            return True
        token = _read_token(API_TOKEN_FILE)
        if token and self.headers.get("Authorization") != "Bearer " + token:
            self._send(401, {"error": "bearer token required"})
            return True
        return False

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise OverflowError("request body too large")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length))

    def _v2_call(self, fn):
        try:
            return fn()
        except NotFoundError as exc:
            return self._send(404, {"error": str(exc)})
        except (DomainError, ValueError, OverflowError) as exc:
            return self._send(400, {"error": str(exc)})
        except PermissionDenied as exc:
            return self._send(403, {"error": str(exc)})
        except ConflictError as exc:
            return self._send(409, {"error": str(exc)})

    def _handle_error(self, exc):
        msg = str(exc)
        if isinstance(exc, NotFoundError):
            return self._send(404, {"error": msg})
        if isinstance(exc, PermissionDenied):
            return self._send(403, {"error": msg})
        if isinstance(exc, (DomainError, ValueError, OverflowError, sqlite3.IntegrityError)):
            return self._send(400, {"error": msg})
        return self._send(500, {"error": msg})

    # ---------------------------------------------------------------- dispatch

    def do_GET(self):
        try:
            if self._reject_browser_origin():
                return
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)
            parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/")]

            # ==== kb 查询路由（单服务合并，deepmemory 上游，H2 kb-server 归入 6260）====
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "kb"] and parts[3] == "browse":
                st, data = UP.upstream("GET", "/v1/memories/libraries")
                if st != 200:
                    return self._send(503 if st == 503 else st, data)
                libs = data.get("libraries", {})
                library = qs.get("library", [""])[0]
                if library and library in libs:
                    libs = {library: libs[library]}
                return self._send(200, {"libraries": libs})
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "kb"] and parts[3] == "constraints":
                ws = qs.get("workspace_id", [UP.DEFAULT_WORKSPACE])[0]
                k = int(qs.get("k", ["50"])[0])
                st, mems = UP.list_memories(ws)
                if st != 200:
                    return self._send(503 if st == 503 else st, {"error": "upstream list failed"})
                bias = [m for m in mems if m.get("library") == "bias"]
                bias.sort(key=lambda m: float(m.get("importance") or 0), reverse=True)
                return self._send(200, {"constraints": bias[:k], "count": len(bias),
                                        "note": "" if bias else "bias 库为空（需存量归类）"})
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "kb"] and parts[3] == "contracts":
                topic = qs.get("topic", [""])[0]
                ws = qs.get("workspace_id", [UP.DEFAULT_WORKSPACE])[0]
                k = int(qs.get("k", ["20"])[0])
                st, mems = UP.list_memories(ws)
                if st != 200:
                    return self._send(503 if st == 503 else st, {"error": "upstream list failed"})
                core = [m for m in mems if m.get("library") == "core"]
                if topic:
                    core = [m for m in core if topic in (m.get("content") or "")]
                core.sort(key=lambda m: float(m.get("importance") or 0), reverse=True)
                return self._send(200, {"contracts": core[:k], "count": len(core)})
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "kb"] and parts[3] == "graph":
                st, data = UP.upstream("GET", "/v1/graph/memories")
                if st != 200:
                    return self._send(503 if st == 503 else st, data)
                return self._send(200, {"graph": data})

            # /v1/literature/attachments/<file>?t=<signed>
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "attachments"]:
                file_name = parts[3]
                token = qs.get("t", [""])[0]
                if not _verify_attachment(file_name, token):
                    return self._send(403, {"error": "invalid or expired attachment token"})
                file_path = os.path.join(ATTACHMENT_DIR, file_name)
                if not os.path.exists(file_path):
                    return self._send(404, {"error": "attachment not found"})
                with open(file_path, "rb") as fh:
                    data = fh.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'inline; filename="{file_name}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return True

            store = get_store()
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "config-schema":
                return self._send(200, {"schema": CONFIG_SCHEMA})
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "config":
                return self._v2_call(lambda: self._send(200, {"config": store.get_settings()}))
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "documents"]:
                doc_id = int(parts[3])
                return self._v2_call(lambda: self._send(200, {"document": store.get_document(doc_id, include_evidence=True)}))
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "evidence"]:
                ev_id = int(parts[3])
                return self._v2_call(lambda: self._send(200, {"evidence": store.get_evidence(ev_id)}))
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "knowledge-browse":
                return self._v2_call(lambda: self._send(200, {"items": store.list_knowledge(
                    workspace_id=qs.get("workspace_id", [""])[0],
                    library=qs.get("library", [None])[0] or None,
                    archived=qs.get("archived", ["false"])[0].lower() == "true",
                    k=int(qs.get("k", ["100"])[0]))}))
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "knowledge-count":
                return self._v2_call(lambda: self._send(200, {"count": store.count_knowledge(
                    workspace_id=qs.get("workspace_id", [""])[0])}))
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "knowledge"]:
                kid = int(parts[3])
                return self._v2_call(lambda: self._send(200, {"knowledge": store.get_knowledge_item(kid)}))
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "documents":
                return self._v2_call(lambda: self._send(200, {"documents": store.list_documents(
                    workspace_id=qs.get("workspace_id", [""])[0],
                    q=qs.get("q", [""])[0],
                    read_status=qs.get("read_status", [None])[0] or None,
                    tags=[t for t in qs.get("tags", [""])[0].split(",") if t],
                    include_archived=qs.get("include_archived", ["false"])[0] == "true",
                )}))
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "graph":
                return self._v2_call(lambda: self._send(200, {"graph": store.graph(
                    workspace_id=qs.get("workspace_id", [""])[0],
                    library=qs.get("library", [None])[0] or None,
                )}))
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "export"] and parts[3] == "bibtex":
                ids = [int(i) for i in qs.get("ids", [""])[0].split(",") if i]
                return self._v2_call(lambda: self._send(200, {"bibtex": store.export_bibtex(ids, workspace_id=qs.get("workspace_id", [""])[0])}))
            return self._send(404, {"error": "not found"})
        except Exception as exc:
            return self._handle_error(exc)

    def do_POST(self):
        try:
            if self._reject_browser_origin():
                return
            path = urllib.parse.urlparse(self.path).path
            parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/")]
            store = get_store()

            # 附件上传：multipart/form-data
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "attachments":
                return self._handle_upload(store)

            body = self._read_body()

            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "config":
                return self._v2_call(lambda: self._send(200, {"config": store.set_settings(body)}))
            # ==== kb/query（单服务合并：本地知识 + deepmemory RRF 融合，N3）====
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "kb"] and parts[3] == "query":
                q = str(body.get("query") or "").strip()
                if not q:
                    return self._send(400, {"error": "query is required"})
                k = int(body.get("k") or 5)
                mode = str(body.get("mode") or "auto")
                ws = str(body.get("workspace_id") or UP.DEFAULT_WORKSPACE)
                lib = body.get("library") or None
                # 本地知识（向量+RRF）——knowledge-only / hybrid
                local_results = []
                if mode != "deepmemory-only":
                    try:
                        local_results = store.search_knowledge(q, k=k * 2, workspace_id=ws, library=lib)
                    except Exception:
                        local_results = []
                # deepmemory 记忆——deepmemory-only / hybrid
                mem_results = []
                if mode != "knowledge-only":
                    payload = {"query": q, "k": k * 2, "include_archived": False, "workspace_id": ws}
                    if lib:
                        payload["library"] = lib
                    st, data = UP.upstream("POST", "/v1/memories/search", payload)
                    if st == 200:
                        mem_results = data.get("results", [])
                # RRF 融合
                RRF_K = 60
                scores, src = {}, {}
                for rank, r in enumerate(mem_results):
                    rid = "mem:" + str(r.get("id"))
                    scores[rid] = scores.get(rid, 0) + 1.0 / (RRF_K + rank + 1)
                    src[rid] = {"kind": "deepmemory", "payload": dict(r)}
                for rank, r in enumerate(local_results):
                    rid = "kn:" + str(r.get("id"))
                    scores[rid] = scores.get(rid, 0) + 1.0 / (RRF_K + rank + 1)
                    src[rid] = {"kind": "literature", "payload": dict(r)}
                ranked = sorted(scores.items(), key=lambda x: -x[1])[:k]
                results = []
                for rid, _ in ranked:
                    it = src[rid]
                    p_ = it["payload"]
                    p_["source"] = it["kind"]
                    results.append(p_)
                # auto：知识量≥50 切纯知识（查询本地 count）
                kn_total = 0
                if mode == "auto":
                    try:
                        kn_total = store.count_knowledge(workspace_id=ws)
                    except Exception:
                        kn_total = 0
                    if kn_total >= 50:
                        results = [r for r in results if r.get("source") == "literature"][:k]
                return self._send(200, {"query": q, "count": len(results), "mode": mode,
                                        "results": results, "knowledge_count": kn_total})
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "documents":
                return self._v2_call(lambda: self._send(200, {"document": store.create_document(body)}))
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "evidence":
                return self._v2_call(lambda: self._send(200, {"evidence": store.create_evidence(body)}))
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "archive-library":
                lib = str(body.get("library") or "").strip()
                if lib not in ("bias", "core", "eco", "project", "runtime"):
                    return self._send(400, {"error": f"invalid library: {lib}"})
                return self._v2_call(lambda: self._send(200, {
                    "archived": lib, "count": store.archive_knowledge_library(
                        lib, workspace_id=str(body.get("workspace_id") or ""),
                        reason=str(body.get("reason") or ""))}))
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "kb-search":
                q = str(body.get("query") or "").strip()
                if not q:
                    return self._send(400, {"error": "query is required"})
                return self._v2_call(lambda: self._send(200, {"results": store.search_knowledge(
                    q, k=int(body.get("k") or 10),
                    workspace_id=str(body.get("workspace_id") or ""),
                    library=body.get("library") or None)}))
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "knowledge"] and parts[3] == "rebuild":
                return self._v2_call(lambda: self._send(200, {"rebuilt": store.rebuild_knowledge_vectors()}))
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "knowledge":
                return self._v2_call(lambda: self._send(200, {"knowledge": store.create_knowledge_item(body)}))
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "claims":
                return self._v2_call(lambda: self._send(200, {"claims": store.claims(
                    str(body.get("q") or ""), workspace_id=str(body.get("workspace_id") or ""))}))
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "graph":
                return self._v2_call(lambda: self._send(200, {"graph": store.graph(
                    workspace_id=str(body.get("workspace_id") or ""),
                    library=body.get("library") or None)}))
            if len(parts) == 3 and parts[:2] == ["v1", "literature"] and parts[2] == "dedupe":
                return self._v2_call(lambda: self._send(200, store.dedupe_check(body.get("candidates") or [])))
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "import"]:
                if parts[3] == "bibtex":
                    return self._v2_call(lambda: self._send(200, store.import_bibtex(
                        str(body.get("text") or ""), workspace_id=str(body.get("workspace_id") or ""),
                        skip_duplicates=bool(body.get("skip_duplicates", True)))))
                if parts[3] == "doi":
                    return self._v2_call(lambda: self._send(200, {"document": store.import_doi(
                        str(body.get("doi") or ""), workspace_id=str(body.get("workspace_id") or ""))}))
            return self._send(404, {"error": "not found"})
        except Exception as exc:
            return self._handle_error(exc)

    def do_PATCH(self):
        try:
            if self._reject_browser_origin():
                return
            path = urllib.parse.urlparse(self.path).path
            parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/")]
            store = get_store()
            body = self._read_body()
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "documents"]:
                return self._v2_call(lambda: self._send(200, {"document": store.update_document(int(parts[3]), body)}))
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "evidence"]:
                return self._v2_call(lambda: self._send(200, {"evidence": store.update_evidence(int(parts[3]), body)}))
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "knowledge"]:
                return self._v2_call(lambda: self._send(200, {"knowledge": store.update_knowledge_item(int(parts[3]), body)}))
            return self._send(404, {"error": "not found"})
        except Exception as exc:
            return self._handle_error(exc)

    def do_DELETE(self):
        try:
            if self._reject_browser_origin():
                return
            path = urllib.parse.urlparse(self.path).path
            parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/")]
            store = get_store()
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "documents"]:
                return self._v2_call(lambda: self._send(200, store.soft_delete_document(int(parts[3]))))
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "evidence"]:
                return self._v2_call(lambda: self._send(200, store.soft_delete_evidence(int(parts[3]))))
            if len(parts) == 4 and parts[:3] == ["v1", "literature", "knowledge"]:
                return self._v2_call(lambda: self._send(200, store.soft_delete_knowledge_item(int(parts[3]))))
            return self._send(404, {"error": "not found"})
        except Exception as exc:
            return self._handle_error(exc)

    def do_OPTIONS(self):
        self._send(403, {"error": "browser origin is not allowed"})

    # ---------------------------------------------------------------- upload

    def _handle_upload(self, store):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return self._send(400, {"error": "invalid Content-Length"})
        if length <= 0 or length > MAX_BODY_BYTES:
            return self._send(413, {"error": "request body too large or empty"})
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            return self._send(400, {"error": "multipart/form-data required"})
        m = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                m = part[len("boundary="):].strip('"')
                break
        if not m:
            return self._send(400, {"error": "boundary missing"})
        raw = self.rfile.read(length)
        boundary = ("--" + m).encode("utf-8")
        chunks = raw.split(boundary)
        file_name = ""
        file_data = None
        workspace_id = ""
        for chunk in chunks:
            if b"filename=" in chunk.split(b"\r\n\r\n", 1)[0]:
                head, _, body = chunk.partition(b"\r\n\r\n")
                fm = None
                for line in head.split(b"\r\n"):
                    if b"filename=" in line:
                        fm = line
                        break
                if fm:
                    file_name = fm.decode("utf-8", "ignore").split("filename=")[1].strip('"').split('"')[0]
                    file_data = body.rstrip(b"\r\n")
            elif b'name="workspace_id"' in chunk.split(b"\r\n\r\n", 1)[0]:
                head, _, body = chunk.partition(b"\r\n\r\n")
                workspace_id = body.rstrip(b"\r\n").decode("utf-8", "ignore").strip()
        if not file_name or file_data is None:
            return self._send(400, {"error": "file part missing"})
        safe_name = os.path.basename(file_name)
        import hashlib
        sha = hashlib.sha256(file_data).hexdigest()
        stored = f"{int(time.time())}-{sha[:12]}-{safe_name}"
        stored_path = os.path.join(ATTACHMENT_DIR, stored)
        with open(stored_path, "wb") as fh:
            fh.write(file_data)
        return self._send(200, {
            "attachment_path": stored,
            "attachment_sha256": sha,
            "size": len(file_data),
            "workspace_id": workspace_id,
            "note": "用该 attachment_path/attachment_sha256 创建或更新文献",
        })


def main():
    init_db()
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"literature server listening on {PORT} (db={DB_PATH})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
