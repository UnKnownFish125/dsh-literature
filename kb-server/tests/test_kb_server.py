"""dsh-literature kb 查询服务单测（plan-v3.1）：mock 上游 deepmemory，验证代理路由。"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SERVER_DIR, "kb-server"))
import kb_server as S  # noqa: E402


class FakeMemoryHandler:
    """mock deepmemory 上游：仅 search/libraries/health/graph 查询端点。"""
    routes = {}
    last_post = {}

    @classmethod
    def reset(cls):
        cls.routes = {
            ("POST", "/v1/memories/search"): {"results": [{"id": 69, "content": "任何对本机进行修改的内容都需要测试机验证通过",
                                                           "type": "preference", "scope": "global",
                                                           "library": "runtime", "importance": 0.95,
                                                           "final_score": 0.8}]},
            ("GET", "/v1/memories/libraries"): {"libraries": {"bias": {"total": 0, "archived": 0},
                                                               "core": {"total": 0, "archived": 0},
                                                               "project": {"total": 5, "archived": 0},
                                                               "runtime": {"total": 305, "archived": 0}}},
            ("GET", "/v1/health"): {"status": "ok", "documents": 305},
            ("GET", "/v1/graph/memories"): {"nodes": [], "edges": []},
            ("GET", "/v1/memories/list"): {"memories": [
                {"id": 28, "content": "用户要求：以后任何重启、进程操作必须先征得用户同意才能执行。",
                 "type": "preference", "scope": "global", "library": "bias", "importance": 0.9},
                {"id": 256, "content": "用户要求后续所有路径一律使用绝对路径表示，以防止混淆。",
                 "type": "preference", "scope": "global", "library": "bias", "importance": 0.85},
                {"id": 30, "content": "修复方案分两层：在 plugin-v3.js 增加 redactSensitive",
                 "type": "fact", "scope": "workspace", "library": "core", "importance": 0.95},
            ]},
        }
        cls.last_post = {}


class FakeMemoryHTTPServer:
    """用真实 HTTP server 包装 FakeMemoryHandler（handler 协议）。"""
    def __init__(self):
        from http.server import BaseHTTPRequestHandler

        class _H(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else {}
                key = (self.command, self.path.split("?")[0])
                routes = FakeMemoryHandler.routes
                if key not in routes:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = routes[key]
                if key[0] == "POST" and key[1] == "/v1/memories/search":
                    # 记录请求供透传断言
                    FakeMemoryHandler.last_post = dict(body)
                    data = dict(data)
                raw = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._handle()

            def do_POST(self):
                self._handle()

            def log_message(self, *args):
                pass

        import http.server
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def shutdown(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class KbServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FakeMemoryHandler.reset()
        cls.mem = FakeMemoryHTTPServer()
        cls.tmp = tempfile.TemporaryDirectory()
        S.DATA_DIR = cls.tmp.name
        S.API_TOKEN_FILE = os.path.join(cls.tmp.name, "api-token")
        S.MEMORY_URL = f"http://127.0.0.1:{cls.mem.port}"
        S._ensure_token()
        cls.token = open(S.API_TOKEN_FILE).read().strip()
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.mem.shutdown()
        cls.tmp.cleanup()

    def req(self, method, path, body=None, token="<default>"):
        data = None if body is None else json.dumps(body).encode("utf-8")
        url = f"http://127.0.0.1:{self.port}" + urllib.parse.quote(path, safe="/?=&,%")
        r = urllib.request.Request(url, data=data, method=method)
        r.add_header("Content-Type", "application/json")
        if token == "<default>":
            token = self.token
        if token:
            r.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_auth(self):
        self.assertEqual(401, self.req("GET", "/v1/literature/health", token=None)[0])
        self.assertEqual(401, self.req("GET", "/v1/literature/health", token="bad")[0])

    def test_health_upstream_ok(self):
        st, body = self.req("GET", "/v1/literature/health")
        self.assertEqual(200, st)
        self.assertEqual("ok", body["upstream_status"])

    def test_kb_query_passthrough_library(self):
        st, body = self.req("POST", "/v1/literature/kb/query",
                            {"query": "测试机", "library": "bias", "k": 3})
        self.assertEqual(200, st)
        self.assertEqual(1, body["count"])
        # 校验透传：mock 记录到 last_post
        self.assertEqual("bias", FakeMemoryHandler.last_post.get("library"))
        self.assertEqual("测试机", FakeMemoryHandler.last_post.get("query"))

    def test_kb_recall_keeps_metadata(self):
        st, body = self.req("POST", "/v1/literature/kb/recall", {"query": "测试机", "k": 2})
        self.assertEqual(200, st)
        r = body["results"][0]
        self.assertIn("final_score", r)  # recall 保留完整元数据

    def test_kb_browse(self):
        st, body = self.req("GET", "/v1/literature/kb/browse")
        self.assertEqual(200, st)
        self.assertIn("runtime", body["libraries"])
        self.assertEqual(305, body["libraries"]["runtime"]["total"])
        st, body = self.req("GET", "/v1/literature/kb/browse?library=project")
        self.assertEqual(200, st)
        self.assertIn("project", body["libraries"])
        self.assertNotIn("runtime", body["libraries"])

    def test_kb_constraints_enumerates_bias(self):
        # bias 库枚举（list 通道，非语义召回）
        st, body = self.req("GET", "/v1/literature/kb/constraints")
        self.assertEqual(200, st)
        self.assertEqual(2, body["count"])  # mock 有 2 条 bias
        self.assertEqual("", body["note"])

    def test_kb_contracts_enumerates_core(self):
        st, body = self.req("GET", "/v1/literature/kb/contracts")
        self.assertEqual(200, st)
        self.assertEqual(1, body["count"])  # mock 有 1 条 core
        self.assertEqual("core", body["contracts"][0]["library"])

    def test_query_requires_query(self):
        st, body = self.req("POST", "/v1/literature/kb/query", {"k": 3})
        self.assertEqual(400, st)

    def test_unknown_route(self):
        st, _ = self.req("GET", "/v1/literature/nonexistent")
        self.assertEqual(404, st)


if __name__ == "__main__":
    unittest.main()
