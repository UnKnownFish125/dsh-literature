"""dsh-literatum 契约 contract-v0.2 验收单测（SA-1 域层 + SA-2 HTTP）。"""
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import urllib.parse

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVER_DIR)
import literature_server as S  # noqa: E402
from literature_domain import DomainError, LiteratumStore, NotFoundError, install_schema  # noqa: E402


class LiteratumDomainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        conn = sqlite3.connect(self.db)
        install_schema(conn)
        conn.commit()
        conn.close()
        self.store = LiteratumStore(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_document_crud_and_soft_delete(self):
        d = self.store.create_document({"title": "认知负荷理论", "authors": ["Sweller"],
                                        "year": 1988, "doi": "10.1/123", "tags": ["教育"], "workspace_id": "w1"})
        self.assertEqual("认知负荷理论", d["title"])
        self.assertEqual(["Sweller"], d["authors"])
        updated = self.store.update_document(d["id"], {"read_status": "reading"})
        self.assertEqual("reading", updated["read_status"])
        self.assertEqual("认知负荷理论", self.store.get_document(d["id"])["title"])
        self.store.soft_delete_document(d["id"])
        with self.assertRaises(NotFoundError):
            self.store.get_document(d["id"])

    def test_evidence_claims_aggregation(self):
        d = self.store.create_document({"title": "工作记忆", "workspace_id": "w1"})
        self.store.create_evidence({"claim": "工作记忆容量有限", "stance": "supporting",
                                    "doc_id": d["id"], "workspace_id": "w1"})
        self.store.create_evidence({"claim": "工作记忆容量有限", "stance": "contradicting",
                                    "doc_id": d["id"], "workspace_id": "w1"})
        res = self.store.claims("工作记忆容量有限", workspace_id="w1")
        self.assertEqual(1, len(res["supporting"]))
        self.assertEqual(1, len(res["contradicting"]))

    def test_knowledge_graph_and_workspace_isolation(self):
        k1 = self.store.create_knowledge_item({"concept": "认知负荷", "workspace_id": "w1"})["id"]
        k2 = self.store.create_knowledge_item({"concept": "工作记忆", "workspace_id": "w1"})["id"]
        self.store.update_knowledge_item(k1, {"relations": [{"source": k1, "target": k2, "relation": "影响"}]})
        g = self.store.graph(workspace_id="w1")
        self.assertEqual(2, len(g["nodes"]))
        self.assertEqual(1, len(g["edges"]))
        self.assertEqual(0, len(self.store.graph(workspace_id="w2")["nodes"]))

    def test_bibtex_import_dedupe_export(self):
        text = '@article{k1, title={论文0号}, author={X and Y}, year={2020}, doi={10.9/0}}'
        res = self.store.import_bibtex(text, workspace_id="w1")
        self.assertEqual(1, res["imported_count"])
        hits = self.store.dedupe_check([{"title": "论文0号", "doi": "10.9/0"}])
        self.assertEqual(1, hits["duplicate_count"])
        out = self.store.export_bibtex([res["imported"][0]["id"]], workspace_id="w1")
        self.assertIn("@article", out)

    def test_document_search_chinese(self):
        self.store.create_document({"title": "认知负荷理论", "workspace_id": "w1"})
        self.store.create_document({"title": "工作记忆容量研究", "workspace_id": "w1"})
        self.assertEqual(1, len(self.store.list_documents(workspace_id="w1", q="认知")))
        self.assertEqual(1, len(self.store.list_documents(workspace_id="w1", q="工作记忆")))
        self.assertEqual(2, len(self.store.list_documents(workspace_id="w1")))


class LiteratumHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        S.DATA_DIR = root
        S.DB_PATH = os.path.join(root, "l.db")
        S.ATTACHMENT_DIR = os.path.join(root, "att")
        S.API_TOKEN_FILE = os.path.join(root, "api-token")
        S.SIGNING_KEY_FILE = os.path.join(root, "sign-key")
        os.makedirs(S.ATTACHMENT_DIR, exist_ok=True)
        S._store = None  # 重置模块级 store 缓存，避免跨测试 DB 路径污染
        S.init_db()
        self.token = open(S.API_TOKEN_FILE).read().strip()
        self.httpd = S.ThreadingHTTPServer(("localhost", 0), S.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://localhost:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def req(self, method, path, body=None, token="<default>", origin=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        url = self.base + urllib.parse.quote(path, safe="/?=&,%")
        r = urllib.request.Request(url, data=data, method=method)
        r.add_header("Content-Type", "application/json")
        if token == "<default>":
            token = self.token
        if token:
            r.add_header("Authorization", f"Bearer {token}")
        if origin:
            r.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_auth_and_origin(self):
        self.assertEqual(401, self.req("POST", "/v1/literatum/documents", {"title": "x"}, token=None)[0])
        self.assertEqual(401, self.req("POST", "/v1/literatum/documents", {"title": "x"}, token="bad")[0])
        self.assertEqual(403, self.req("POST", "/v1/literatum/documents", {"title": "x"}, origin="http://evil")[0])

    def test_full_acceptance_flow(self):
        s, r = self.req("POST", "/v1/literatum/documents",
                        {"title": "认知负荷理论", "authors": ["Sweller"], "doi": "10.1/123", "workspace_id": "w1"})
        self.assertEqual(200, s)
        d1 = r["document"]["id"]
        s, r = self.req("POST", "/v1/literatum/documents", {"title": "工作记忆", "workspace_id": "w1"})
        d2 = r["document"]["id"]
        s, r = self.req("GET", "/v1/literatum/documents?q=" + urllib.parse.quote("认知") + "&workspace_id=w1")
        self.assertEqual(200, s)
        self.assertEqual(1, len(r["documents"]))
        s, r = self.req("PATCH", f"/v1/literatum/documents/{d1}", {"read_status": "reading"})
        self.assertEqual("reading", r["document"]["read_status"])
        # evidence + claims
        s, r = self.req("POST", "/v1/literatum/evidence",
                        {"claim": "容量有限", "stance": "supporting", "doc_id": d2, "workspace_id": "w1"})
        e1 = r["evidence"]["id"]
        s, r = self.req("POST", "/v1/literatum/evidence",
                        {"claim": "容量有限", "stance": "contradicting", "doc_id": d2, "workspace_id": "w1"})
        s, r = self.req("POST", "/v1/literatum/claims", {"q": "容量有限", "workspace_id": "w1"})
        self.assertEqual(1, len(r["claims"]["supporting"]))
        self.assertEqual(1, len(r["claims"]["contradicting"]))
        # knowledge + graph
        s, r = self.req("POST", "/v1/literatum/knowledge",
                        {"concept": "认知负荷", "summary": "x", "workspace_id": "w1", "sources": [e1]})
        k1 = r["knowledge"]["id"]
        s, r = self.req("POST", "/v1/literatum/knowledge", {"concept": "工作记忆", "workspace_id": "w1"})
        k2 = r["knowledge"]["id"]
        s, r = self.req("PATCH", f"/v1/literatum/knowledge/{k1}",
                        {"relations": [{"source": k1, "target": k2, "relation": "影响"}]})
        self.assertEqual(200, s)
        s, r = self.req("GET", "/v1/literatum/graph?workspace_id=w1")
        self.assertEqual(2, len(r["graph"]["nodes"]))
        self.assertEqual(1, len(r["graph"]["edges"]))
        s, r = self.req("GET", "/v1/literatum/graph?workspace_id=w2")
        self.assertEqual(0, len(r["graph"]["nodes"]))
        # bibtex import + dedupe + export
        lines = [f"@article{{k{i}, title={{论文{i}号}}, year={{202{i%3}}}, doi={{10.9/{i}}}}}" for i in range(5)]
        s, r = self.req("POST", "/v1/literatum/import/bibtex", {"text": "\n".join(lines), "workspace_id": "w1"})
        self.assertEqual(5, r["imported_count"])
        s, r = self.req("POST", "/v1/literatum/dedupe", {"candidates": [{"title": "论文0号", "doi": "10.9/0"}]})
        self.assertEqual(1, r["duplicate_count"])
        s, r = self.req("GET", "/v1/literatum/export/bibtex?ids=2&workspace_id=w1")
        self.assertEqual(200, s)
        self.assertIn("@article", r["bibtex"])

    def raw_status(self, path, token=None):
        """二进制/非 JSON 响应只取状态码。"""
        url = self.base + urllib.parse.quote(path, safe="/?=&,.%")
        r = urllib.request.Request(url, method="GET")
        if token is None:
            token = self.token
        if token:
            r.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def test_attachment_upload_and_signed_fetch(self):
        import uuid as _uuid
        boundary = "B" + _uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"paper.pdf\"\r\n"
                "Content-Type: application/pdf\r\n\r\n").encode() + b"%PDF-1.4" + f"\r\n--{boundary}--\r\n".encode()
        r = urllib.request.Request(self.base + "/v1/literatum/attachments", data=body, method="POST")
        r.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        r.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(r, timeout=10) as resp:
            up = json.loads(resp.read())
        self.assertTrue(up["attachment_path"])
        ap = up["attachment_path"]
        sk = open(S.SIGNING_KEY_FILE).read().strip()
        exp = int(time.time()) + 300
        sig = hmac.new(sk.encode(), f"{ap}.{exp}".encode(), hashlib.sha256).hexdigest()
        self.assertEqual(200, self.raw_status(f"/v1/literatum/attachments/{ap}?t={exp}.{sig}"))
        self.assertEqual(403, self.raw_status(f"/v1/literatum/attachments/{ap}?t={exp}.bad"))
        self.assertEqual(403, self.raw_status(f"/v1/literatum/attachments/{ap}?t={int(time.time())-3600}.{sig}"))
        self.assertIn(self.raw_status("/v1/literatum/attachments/..%2F..%2Fetc%2Fpasswd?t=x"), (403, 404))


if __name__ == "__main__":
    unittest.main()
