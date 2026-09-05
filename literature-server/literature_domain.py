#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_domain.py — dsh-literature 域模型与存储层（独立 sqlite，不依赖 deepmemory）
文献(Document) → 证据(Evidence) → 知识(KnowledgeItem) 派生链 + 概念网络。

契约：contract-v0.2 §4.1 存储 / §4.2 API 语义。全部实体支持软删（deleted_at），
workspace_id 硬过滤（查询默认按 workspace 收窄，联结表经两端推导）。
"""

import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import uuid

LIBRARY_SCHEMA_VERSION = 1

VALID_TYPES = ("paper", "book", "report", "web")
VALID_STANCES = ("supporting", "contradicting", "contextual")
READ_STATUSES = ("unread", "reading", "intensive", "read")
LIFECYCLE_STATUSES = ("active", "archived")


class DomainError(Exception):
    pass


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class PermissionDenied(DomainError):
    pass


def _now():
    return time.time()


def _json_dumps(value):
    return json.dumps(value or [], ensure_ascii=False)


def _json_loads(value, default=None):
    try:
        return json.loads(value) if value else (default if default is not None else [])
    except (TypeError, ValueError):
        return default if default is not None else []


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL DEFAULT 'paper' CHECK(type IN ('paper','book','report','web')),
  title TEXT NOT NULL DEFAULT '',
  authors_json TEXT NOT NULL DEFAULT '[]',
  year INTEGER,
  journal TEXT NOT NULL DEFAULT '',
  doi TEXT NOT NULL DEFAULT '',
  isbn TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  attachment_path TEXT NOT NULL DEFAULT '',
  attachment_sha256 TEXT NOT NULL DEFAULT '',
  tags_json TEXT NOT NULL DEFAULT '[]',
  read_status TEXT NOT NULL DEFAULT 'unread' CHECK(read_status IN ('unread','reading','intensive','read')),
  lifecycle_status TEXT NOT NULL DEFAULT 'active' CHECK(lifecycle_status IN ('active','archived')),
  deleted_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  workspace_id TEXT NOT NULL DEFAULT '',
  full_text TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_documents_ws ON documents(workspace_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_documents_doi ON documents(doi) WHERE doi != '';

CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  claim TEXT NOT NULL DEFAULT '',
  stance TEXT NOT NULL DEFAULT 'contextual' CHECK(stance IN ('supporting','contradicting','contextual')),
  evidence_text TEXT NOT NULL DEFAULT '',
  doc_id INTEGER REFERENCES documents(id),
  chapter_anchor TEXT NOT NULL DEFAULT '',
  page TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0.5,
  note TEXT NOT NULL DEFAULT '',
  deleted_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  workspace_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_evidence_ws ON evidence(workspace_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_evidence_claim ON evidence(claim);

CREATE TABLE IF NOT EXISTS knowledge_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  concept TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  deleted_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  workspace_id TEXT NOT NULL DEFAULT '',
  library TEXT NOT NULL DEFAULT 'runtime',
  archived INTEGER NOT NULL DEFAULT 0,
  source_memory_id INTEGER DEFAULT NULL,
  parent_id INTEGER REFERENCES knowledge_items(id),
  node_depth INTEGER NOT NULL DEFAULT 0,
  node_kind TEXT NOT NULL DEFAULT 'item',
  category_id INTEGER REFERENCES categories(id),
  node_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_knowledge_ws ON knowledge_items(workspace_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_parent ON knowledge_items(parent_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_cat ON knowledge_items(category_id);

CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  parent_id INTEGER REFERENCES categories(id),
  scope TEXT NOT NULL DEFAULT 'workspace',
  workspace_id TEXT NOT NULL DEFAULT '',
  node_depth INTEGER NOT NULL DEFAULT 0,
  order_index INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  deleted_at REAL
);
CREATE INDEX IF NOT EXISTS idx_cat_ws ON categories(workspace_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_cat_parent ON categories(parent_id);

CREATE TRIGGER IF NOT EXISTS knowledge_library_check_insert
BEFORE INSERT ON knowledge_items BEGIN
  SELECT CASE WHEN NEW.library NOT IN ('bias','core','eco','project','runtime')
    THEN RAISE(ABORT, 'invalid library') END;
END;

CREATE TRIGGER IF NOT EXISTS knowledge_library_check_update
BEFORE UPDATE ON knowledge_items BEGIN
  SELECT CASE WHEN NEW.library NOT IN ('bias','core','eco','project','runtime')
    THEN RAISE(ABORT, 'invalid library') END;
  SELECT CASE WHEN NEW.archived=1 AND NEW.library='bias'
    THEN RAISE(ABORT, 'bias library cannot be archived') END;
END;

CREATE TABLE IF NOT EXISTS knowledge_relations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER NOT NULL REFERENCES knowledge_items(id),
  target_id INTEGER NOT NULL REFERENCES knowledge_items(id),
  relation TEXT NOT NULL DEFAULT '',
  workspace_id TEXT NOT NULL DEFAULT '',
  deleted_at REAL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_krel_ws ON knowledge_relations(workspace_id, deleted_at);

CREATE TABLE IF NOT EXISTS evidence_source (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  evidence_id INTEGER NOT NULL REFERENCES evidence(id),
  knowledge_item_id INTEGER NOT NULL REFERENCES knowledge_items(id),
  workspace_id TEXT NOT NULL DEFAULT '',
  deleted_at REAL
);
CREATE INDEX IF NOT EXISTS idx_esrc_ws ON evidence_source(workspace_id, deleted_at);

CREATE TABLE IF NOT EXISTS memory_archive (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id INTEGER UNIQUE,          -- deepmemory documents.id（溯源锚点）
  summary TEXT NOT NULL DEFAULT '',  -- 记忆摘要（deepmemory content）
  library TEXT NOT NULL DEFAULT 'runtime',
  scope TEXT NOT NULL DEFAULT '',
  memory_type TEXT NOT NULL DEFAULT '',
  importance REAL NOT NULL DEFAULT 0,
  workspace_id TEXT NOT NULL DEFAULT '',
  source_count INTEGER NOT NULL DEFAULT 0,
  sources_json TEXT NOT NULL DEFAULT '[]',  -- 原始对话（脱敏版，export-archive deliver）
  created_at REAL NOT NULL,          -- deepmemory created_at
  ingested_at REAL NOT NULL,         -- 本库 ingest 时间
  status TEXT NOT NULL DEFAULT 'raw' CHECK(status IN ('raw','staged','processed'))
);
CREATE INDEX IF NOT EXISTS idx_memarch_ws ON memory_archive(workspace_id);
CREATE INDEX IF NOT EXISTS idx_memarch_status ON memory_archive(status);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT '',
  updated_at REAL
);

CREATE TABLE IF NOT EXISTS fts_documents (
  title TEXT,
  authors TEXT,
  journal TEXT,
  tags TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS documents_title_fts USING fts5(
  title, authors, journal, tags, tokenize='trigram'
);
CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
  claim, evidence_text, tokenize='trigram'
);
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
  concept, summary, tokenize='trigram'
);
"""


def install_schema(conn):
    conn.executescript(SCHEMA)


class LiteratumStore:
    """literature 域层：所有读写自带 workspace 硬过滤。"""

    def __init__(self, db_path):
        self.db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ------------------------------------------------------------ settings

    def get_settings(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def set_settings(self, values):
        now = _now()
        with self._connect() as conn:
            for key, value in (values or {}).items():
                conn.execute(
                    "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?)"
                    " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (str(key), json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value, now),
                )
        return self.get_settings()

    # ------------------------------------------------------------ documents

    def _doc_from_row(self, row, include_evidence=False):
        d = dict(row)
        d["authors"] = _json_loads(d.pop("authors_json", None))
        d["tags"] = _json_loads(d.pop("tags_json", None))
        if include_evidence:
            with self._connect() as conn:
                evs = conn.execute(
                    "SELECT id, claim, stance, evidence_text, doc_id, chapter_anchor, page,"
                    " confidence, note, created_at, updated_at FROM evidence"
                    " WHERE doc_id=? AND deleted_at IS NULL ORDER BY id", (d["id"],),
                ).fetchall()
            d["evidence"] = [dict(e) for e in evs]
        return d

    def create_document(self, payload):
        now = _now()
        title = str(payload.get("title") or "").strip()
        if not title:
            raise DomainError("title is required")
        type_ = payload.get("type") or "paper"
        if type_ not in VALID_TYPES:
            raise DomainError(f"invalid type: {type_}")
        workspace_id = str(payload.get("workspace_id") or "")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO documents (type, title, authors_json, year, journal, doi, isbn, url,"
                " attachment_path, attachment_sha256, tags_json, read_status, lifecycle_status,"
                " created_at, updated_at, workspace_id, full_text)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    type_, title,
                    _json_dumps(payload.get("authors")),
                    payload.get("year") or None,
                    str(payload.get("journal") or ""),
                    str(payload.get("doi") or "").strip(),
                    str(payload.get("isbn") or "").strip(),
                    str(payload.get("url") or ""),
                    str(payload.get("attachment_path") or ""),
                    str(payload.get("attachment_sha256") or ""),
                    _json_dumps(payload.get("tags")),
                    payload.get("read_status") or "unread",
                    payload.get("lifecycle_status") or "active",
                    now, now, workspace_id,
                    str(payload.get("full_text") or ""),
                ),
            )
            doc_id = cur.lastrowid
            self._fts_document(conn, doc_id, title, payload.get("authors"), payload.get("journal"), payload.get("tags"))
        return self.get_document(doc_id)

    def _fts_document(self, conn, doc_id, title, authors, journal, tags):
        conn.execute(
            "INSERT INTO documents_title_fts (rowid, title, authors, journal, tags) VALUES (?,?,?,?,?)",
            (doc_id, title or "", " ".join(str(a) for a in (authors or [])),
             str(journal or ""), " ".join(str(t) for t in (tags or []))),
        )

    def list_documents(self, workspace_id="", q="", read_status=None, tags=None, include_archived=False):
        with self._connect() as conn:
            if q and q.strip():
                q = q.strip()
                rows = conn.execute(
                    "SELECT d.* FROM documents d JOIN documents_title_fts f ON f.rowid=d.id"
                    " WHERE d.workspace_id=? AND d.deleted_at IS NULL AND documents_title_fts MATCH ?"
                    " AND (? OR d.lifecycle_status='active') ORDER BY d.updated_at DESC LIMIT 200",
                    (workspace_id, q, bool(include_archived)),
                ).fetchall()
                # 短查询（<3 字符）trigram 无法匹配子串 → LIKE 兜底
                if not rows and len(q) < 3:
                    rows = conn.execute(
                        "SELECT * FROM documents WHERE workspace_id=? AND deleted_at IS NULL"
                        " AND (title LIKE ? OR journal LIKE ?)"
                        " AND (? OR lifecycle_status='active') ORDER BY updated_at DESC LIMIT 200",
                        (workspace_id, f"%{q}%", f"%{q}%", bool(include_archived)),
                    ).fetchall()
            else:
                sql = ("SELECT * FROM documents WHERE workspace_id=? AND deleted_at IS NULL"
                       + ("" if include_archived else " AND lifecycle_status='active'"))
                args = [workspace_id]
                if read_status:
                    sql += " AND read_status=?"
                    args.append(read_status)
                if tags:
                    for t in tags:
                        sql += " AND tags_json LIKE ?"
                        args.append(f'%"{t}"%')
                sql += " ORDER BY updated_at DESC LIMIT 200"
                rows = conn.execute(sql, args).fetchall()
        return [self._doc_from_row(r) for r in rows]

    def get_document(self, doc_id, include_evidence=False):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id=? AND deleted_at IS NULL", (int(doc_id),),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"document not found: {doc_id}")
        return self._doc_from_row(row, include_evidence=include_evidence)

    def update_document(self, doc_id, changes):
        allowed = ("type", "title", "authors", "year", "journal", "doi", "isbn", "url",
                   "attachment_path", "attachment_sha256", "tags", "read_status", "lifecycle_status")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id=? AND deleted_at IS NULL", (int(doc_id),),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"document not found: {doc_id}")
            fields = {}
            for key in allowed:
                if key in changes:
                    fields[key] = changes[key]
            if not fields:
                return self.get_document(doc_id)
            if "type" in fields and fields["type"] not in VALID_TYPES:
                raise DomainError(f"invalid type: {fields['type']}")
            if "read_status" in fields and fields["read_status"] not in READ_STATUSES:
                raise DomainError(f"invalid read_status: {fields['read_status']}")
            if "lifecycle_status" in fields and fields["lifecycle_status"] not in LIFECYCLE_STATUSES:
                raise DomainError(f"invalid lifecycle_status: {fields['lifecycle_status']}")
            assignments = []
            vals = []
            for key, value in fields.items():
                if key in ("authors", "tags"):
                    assignments.append(("authors_json" if key == "authors" else "tags_json") + "=?")
                    vals.append(_json_dumps(value))
                else:
                    assignments.append(key + "=?")
                    vals.append(value if value is not None else "")
            assignments.append("updated_at=?")
            vals.append(_now())
            vals.append(int(doc_id))
            conn.execute(f"UPDATE documents SET {', '.join(assignments)} WHERE id=?", vals)
            if "title" in fields or "authors" in fields or "journal" in fields or "tags" in fields:
                conn.execute("DELETE FROM documents_title_fts WHERE rowid=?", (int(doc_id),))
                self._fts_document(conn, int(doc_id), fields.get("title", row["title"]),
                                   fields.get("authors", _json_loads(row["authors_json"])),
                                   fields.get("journal", row["journal"]),
                                   fields.get("tags", _json_loads(row["tags_json"])))
        return self.get_document(doc_id)

    def soft_delete_document(self, doc_id):
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE documents SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
                (_now(), _now(), int(doc_id)),
            )
            if cur.rowcount == 0:
                raise NotFoundError(f"document not found: {doc_id}")
            conn.execute("DELETE FROM documents_title_fts WHERE rowid=?", (int(doc_id),))
        return {"deleted": True, "id": int(doc_id)}

    # ------------------------------------------------------------ evidence

    def _evidence_from_row(self, row):
        return dict(row)

    def create_evidence(self, payload):
        claim = str(payload.get("claim") or "").strip()
        if not claim:
            raise DomainError("claim is required")
        stance = payload.get("stance") or "contextual"
        if stance not in VALID_STANCES:
            raise DomainError(f"invalid stance: {stance}")
        doc_id = payload.get("doc_id")
        workspace_id = str(payload.get("workspace_id") or "")
        now = _now()
        with self._connect() as conn:
            if doc_id:
                d = conn.execute(
                    "SELECT id FROM documents WHERE id=? AND deleted_at IS NULL", (int(doc_id),),
                ).fetchone()
                if d is None:
                    raise NotFoundError(f"document not found: {doc_id}")
            cur = conn.execute(
                "INSERT INTO evidence (claim, stance, evidence_text, doc_id, chapter_anchor, page,"
                " confidence, note, created_at, updated_at, workspace_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (claim, stance, str(payload.get("evidence_text") or ""),
                 int(doc_id) if doc_id else None,
                 str(payload.get("chapter_anchor") or ""), str(payload.get("page") or ""),
                 float(payload.get("confidence") or 0.5), str(payload.get("note") or ""),
                 now, now, workspace_id),
            )
            ev_id = cur.lastrowid
            conn.execute(
                "INSERT INTO evidence_fts (rowid, claim, evidence_text) VALUES (?,?,?)",
                (ev_id, claim, str(payload.get("evidence_text") or "")),
            )
        return self.get_evidence(ev_id)

    def get_evidence(self, ev_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence WHERE id=? AND deleted_at IS NULL", (int(ev_id),),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"evidence not found: {ev_id}")
        return self._evidence_from_row(row)

    def update_evidence(self, ev_id, changes):
        allowed = ("claim", "stance", "evidence_text", "doc_id", "chapter_anchor",
                   "page", "confidence", "note")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence WHERE id=? AND deleted_at IS NULL", (int(ev_id),),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"evidence not found: {ev_id}")
            fields = {k: v for k, v in changes.items() if k in allowed}
            if not fields:
                return self.get_evidence(ev_id)
            if "stance" in fields and fields["stance"] not in VALID_STANCES:
                raise DomainError(f"invalid stance: {fields['stance']}")
            assignments = [f"{k}=?" for k in fields] + ["updated_at=?"]
            vals = list(fields.values()) + [_now(), int(ev_id)]
            conn.execute(f"UPDATE evidence SET {', '.join(assignments)} WHERE id=?", vals)
            if "claim" in fields or "evidence_text" in fields:
                conn.execute("DELETE FROM evidence_fts WHERE rowid=?", (int(ev_id),))
                conn.execute(
                    "INSERT INTO evidence_fts (rowid, claim, evidence_text) VALUES (?,?,?)",
                    (int(ev_id), fields.get("claim", row["claim"]),
                     fields.get("evidence_text", row["evidence_text"])),
                )
        return self.get_evidence(ev_id)

    def soft_delete_evidence(self, ev_id):
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE evidence SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
                (_now(), _now(), int(ev_id)),
            )
            if cur.rowcount == 0:
                raise NotFoundError(f"evidence not found: {ev_id}")
            conn.execute("DELETE FROM evidence_fts WHERE rowid=?", (int(ev_id),))
        return {"deleted": True, "id": int(ev_id)}

    def claims(self, claim, workspace_id=""):
        """同一主张全部证据（support/contradict 聚合）。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence WHERE workspace_id=? AND deleted_at IS NULL"
                " AND (claim=? OR claim LIKE ?) ORDER BY id",
                (workspace_id, claim, "%" + claim + "%"),
            ).fetchall()
        results = [dict(r) for r in rows]
        return {
            "claim": claim,
            "supporting": [r for r in results if r["stance"] == "supporting"],
            "contradicting": [r for r in results if r["stance"] == "contradicting"],
            "contextual": [r for r in results if r["stance"] == "contextual"],
            "total": len(results),
        }

    # ------------------------------------------------------------ categories (树)

    def create_category(self, payload):
        name = str(payload.get("name") or "").strip()
        if not name:
            raise DomainError("name is required")
        workspace_id = str(payload.get("workspace_id") or "")
        scope = str(payload.get("scope") or "workspace")
        parent_id = payload.get("parent_id")
        now = _now()
        with self._connect() as conn:
            depth = 0
            if parent_id:
                p = conn.execute("SELECT node_depth FROM categories WHERE id=? AND deleted_at IS NULL",
                                 (int(parent_id),)).fetchone()
                if not p:
                    raise DomainError("parent category not found")
                depth = p["node_depth"] + 1
            cur = conn.execute(
                "INSERT INTO categories (name, parent_id, scope, workspace_id, node_depth, order_index,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (name, int(parent_id) if parent_id else None, scope, workspace_id, depth,
                 int(payload.get("order_index") or 0), now, now))
        return self.get_category(cur.lastrowid)

    def get_category(self, cid):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM categories WHERE id=? AND deleted_at IS NULL", (int(cid),)).fetchone()
        if not row:
            raise NotFoundError(f"category not found: {cid}")
        return dict(row)

    def list_categories(self, workspace_id="", scope=None):
        with self._connect() as conn:
            sql = "SELECT * FROM categories WHERE deleted_at IS NULL"
            args = []
            if workspace_id:
                sql += " AND workspace_id=?"
                args.append(workspace_id)
            if scope:
                sql += " AND scope=?"
                args.append(scope)
            sql += " ORDER BY node_depth, order_index, id"
            rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def update_category(self, cid, changes):
        allowed = ("name", "parent_id", "order_index")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM categories WHERE id=? AND deleted_at IS NULL", (int(cid),)).fetchone()
            if not row:
                raise NotFoundError(f"category not found: {cid}")
            if "parent_id" in changes:
                pid = changes.get("parent_id")
                depth = 0 if pid is None else (
                    conn.execute("SELECT node_depth FROM categories WHERE id=? AND deleted_at IS NULL",
                                 (int(pid),)).fetchone()["node_depth"] + 1)
                conn.execute("UPDATE categories SET parent_id=?, node_depth=?, updated_at=? WHERE id=?",
                             (int(pid) if pid else None, depth, _now(), int(cid)))
            fields = {k: v for k, v in changes.items() if k in ("name", "order_index")}
            if fields:
                sets = [f"{k}=?" for k in fields] + ["updated_at=?"]
                conn.execute(f"UPDATE categories SET {', '.join(sets)} WHERE id=?",
                             list(fields.values()) + [_now(), int(cid)])
        return self.get_category(cid)

    def soft_delete_category(self, cid):
        with self._connect() as conn:
            cur = conn.execute("UPDATE categories SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                               (_now(), int(cid)))
            if not cur.rowcount:
                raise NotFoundError(f"category not found: {cid}")
            # 子类别/子知识级联软删
            conn.execute("UPDATE categories SET deleted_at=? WHERE parent_id=? AND deleted_at IS NULL",
                         (_now(), int(cid)))
            conn.execute("UPDATE knowledge_items SET deleted_at=? WHERE category_id=? AND deleted_at IS NULL",
                         (_now(), int(cid)))
        return {"deleted": cid}

    def subtree_of_category(self, cid, workspace_id=""):
        """回收CTE取某类别整棵子树（含自身）。workspace 隔离：需传 workspace_id，锚点必须属于该区。"""
        if not str(workspace_id or "").strip():
            raise DomainError("workspace_id is required (default-isolation)")
        with self._connect() as conn:
            root = conn.execute("SELECT workspace_id, node_depth FROM categories WHERE id=? AND deleted_at IS NULL",
                                (int(cid),)).fetchone()
            if not root:
                raise NotFoundError(f"category not found: {cid}")
            # 锚点必须属于请求区；跨区访问需 ACL（一期默认隔离，跨区尚未授权）
            if root["workspace_id"] != workspace_id:
                raise PermissionDenied("cross-workspace category access not authorized")
            cat_ids = conn.execute(
                "WITH RECURSIVE t AS (SELECT id FROM categories WHERE id=? AND workspace_id=? UNION ALL"
                " SELECT c.id FROM categories c JOIN t ON c.parent_id=t.id AND c.workspace_id=?)"
                " SELECT id FROM t", (int(cid), workspace_id, workspace_id)).fetchall()
            ids = [r["id"] for r in cat_ids]
            if not ids:
                return {"categories": [], "knowledge": []}
            ph = ",".join("?" * len(ids))
            cats = conn.execute(f"SELECT * FROM categories WHERE id IN ({ph}) AND deleted_at IS NULL ORDER BY node_depth,order_index", ids).fetchall()
            know = conn.execute(f"SELECT * FROM knowledge_items WHERE category_id IN ({ph}) AND deleted_at IS NULL ORDER BY node_depth,node_order", ids).fetchall()
        return {"categories": [dict(r) for r in cats], "knowledge": [dict(r) for r in know]}

    def subtree_of_knowledge(self, kid, workspace_id=""):
        """回收CTE取某知识节点整棵子知识树（含自身）。workspace 隔离：需传 workspace_id，锚点必须属于该区。"""
        if not str(workspace_id or "").strip():
            raise DomainError("workspace_id is required (default-isolation)")
        with self._connect() as conn:
            root = conn.execute("SELECT workspace_id, node_depth FROM knowledge_items WHERE id=? AND deleted_at IS NULL",
                                (int(kid),)).fetchone()
            if not root:
                raise NotFoundError(f"knowledge not found: {kid}")
            if root["workspace_id"] != workspace_id:
                raise PermissionDenied("cross-workspace knowledge access not authorized")
            ids = conn.execute(
                "WITH RECURSIVE t AS (SELECT id FROM knowledge_items WHERE id=? AND workspace_id=? UNION ALL"
                " SELECT k.id FROM knowledge_items k JOIN t ON k.parent_id=t.id AND k.workspace_id=?)"
                " SELECT id FROM t", (int(kid), workspace_id, workspace_id)).fetchall()
            kid_ids = [r["id"] for r in ids]
            if not kid_ids:
                return []
            ph = ",".join("?" * len(kid_ids))
            rows = conn.execute(f"SELECT * FROM knowledge_items WHERE id IN ({ph}) AND deleted_at IS NULL ORDER BY node_depth,node_order", kid_ids).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ knowledge
    def create_knowledge_item(self, payload):
        concept = str(payload.get("concept") or "").strip()
        if not concept:
            raise DomainError("concept is required")
        workspace_id = str(payload.get("workspace_id") or "")
        library = str(payload.get("library") or "runtime")
        if library not in ("bias", "core", "eco", "project", "runtime"):
            raise DomainError(f"invalid library: {library}")
        archived = int(bool(payload.get("archived")))
        if archived and library == "bias":
            raise DomainError("bias library cannot be archived")
        parent_id = payload.get("parent_id")
        node_kind = str(payload.get("node_kind") or "item")
        if node_kind not in ("item", "root", "theory", "support", "evidence"):
            node_kind = "item"
        category_id = payload.get("category_id")
        node_depth = int(payload.get("node_depth") or 0)
        node_order = int(payload.get("node_order") or 0)
        # parent 存在则自动算 depth+1
        if parent_id:
            with self._connect() as _c:
                _p = _c.execute("SELECT node_depth FROM knowledge_items WHERE id=? AND deleted_at IS NULL",
                                (int(parent_id),)).fetchone()
            if not _p:
                raise DomainError("parent knowledge item not found")
            node_depth = _p["node_depth"] + 1
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO knowledge_items (concept, summary, notes, library, archived,"
                " source_memory_id, parent_id, node_depth, node_kind, category_id, node_order,"
                " created_at, updated_at, workspace_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (concept, str(payload.get("summary") or ""), str(payload.get("notes") or ""),
                 library, archived,
                 int(payload["source_memory_id"]) if payload.get("source_memory_id") else None,
                 int(parent_id) if parent_id else None, node_depth, node_kind,
                 int(category_id) if category_id else None, node_order,
                 now, now, workspace_id),
            )
            kid = cur.lastrowid
            conn.execute("INSERT INTO knowledge_fts (rowid, concept, summary) VALUES (?,?,?)",
                         (kid, concept, str(payload.get("summary") or "")))
            # relations: [{source: id|concept, target: id|concept, relation}]
            relations = payload.get("relations") or []
            for rel in relations:
                self._add_relation(conn, kid, rel, workspace_id, now)
            # sources: [evidence.id...]
            for eid in (payload.get("sources") or []):
                conn.execute(
                    "INSERT INTO evidence_source (evidence_id, knowledge_item_id, workspace_id, deleted_at)"
                    " VALUES (?,?,?,NULL)",
                    (int(eid), kid, workspace_id),
                )
        # 向量化入库（v1.1 第 1 步：knowledge → jina 768 维 → literature 自有 FAISS）
        try:
            self._vectorize_knowledge([kid])
        except Exception:
            pass  # 向量失败不阻断入库（可后续 rebuild 补）
        return self.get_knowledge_item(kid)

    def _vectorize_knowledge(self, kid_ids):
        """为指定 knowledge_items 生成向量并写入 literature 知识 FAISS（去重幂等）。"""
        import literature_vectors as V
        if not kid_ids:
            return 0
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, concept, summary FROM knowledge_items WHERE deleted_at IS NULL"
                " AND id IN (%s)" % ",".join("?" * len(kid_ids)),
                kid_ids,
            ).fetchall()
        if not rows:
            return 0
        texts = [f"{r['concept']} {r['summary']}".strip() for r in rows]
        vectors = V.embed_texts(texts)
        return V.add_vectors([r["id"] for r in rows], vectors)

    def rebuild_knowledge_vectors(self):
        """全量重建知识向量索引（POST /v1/literature/knowledge/rebuild）。"""
        import literature_vectors as V
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, concept, summary FROM knowledge_items WHERE deleted_at IS NULL"
            ).fetchall()
        if not rows:
            V.rebuild([])
            return 0
        texts = [f"{r['concept']} {r['summary']}".strip() for r in rows]
        ids = [r["id"] for r in rows]
        batch = 64
        vectors = []
        for i in range(0, len(rows), batch):
            vectors.extend(V.embed_texts(texts[i:i + batch]))
        V.rebuild(list(zip(ids, texts)))
        return len(ids)

    def archive_knowledge_library(self, library, workspace_id="", reason=""):
        """归档整个库（active→archived）。bias 拒归档（触发器+服务端双重守卫）。
        workspace 隔离：空 workspace 代表全库会导致跨工作区批量归档，故要求显式 workspace_id。
        跨区归档需授权（ACL 后续），此处默认拒绝空（默认隔离兜底）。"""
        if library == "bias":
            raise DomainError("bias library cannot be archived")
        if not str(workspace_id or "").strip():
            raise DomainError("workspace_id is required to archive a library (default-isolation)")
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE knowledge_items SET archived=1, updated_at=? WHERE deleted_at IS NULL"
                " AND archived=0 AND library=? AND workspace_id=?",
                (now, library, workspace_id))
        return cur.rowcount

    def list_knowledge(self, workspace_id="", library=None, archived=False, k=100):
        """列出 knowledge_items（供 browse/归档枚举）。"""
        with self._connect() as conn:
            sql = "SELECT * FROM knowledge_items WHERE deleted_at IS NULL"
            args = []
            if workspace_id:
                sql += " AND workspace_id=?"
                args.append(workspace_id)
            if library:
                sql += " AND library=?"
                args.append(library)
            if archived:
                sql += " AND archived=1"
            else:
                sql += " AND archived=0"
            sql += " ORDER BY id DESC LIMIT ?"
            args.append(min(k, 1000))
            rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def count_knowledge(self, workspace_id=""):
        with self._connect() as conn:
            sql = "SELECT COUNT(*) AS c FROM knowledge_items WHERE deleted_at IS NULL AND archived=0"
            args = []
            if workspace_id:
                sql += " AND workspace_id=?"
                args.append(workspace_id)
            row = conn.execute(sql, args).fetchone()
        return row["c"] if row else 0

    def ingest_memory_archive(self, memories):
        """deepmemory export-archive 结果 → memory_archive 原料归档层（幂等：按 memory_id 去重）。"""
        if not memories:
            return 0
        now = _now()
        added = 0
        with self._connect() as conn:
            for m in memories:
                mid = m.get("id")
                if mid is None:
                    continue
                exists = conn.execute(
                    "SELECT id FROM memory_archive WHERE memory_id=?", (int(mid),)).fetchone()
                if exists:
                    continue
                tags = m.get("tags") or {}
                sources = m.get("sources") or []
                conn.execute(
                    "INSERT INTO memory_archive (memory_id, summary, library, scope, memory_type,"
                    " importance, workspace_id, source_count, sources_json, created_at, ingested_at, status)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (int(mid), str(m.get("summary") or ""), str(tags.get("library") or "runtime"),
                     str(tags.get("scope") or ""), str(tags.get("type") or ""),
                     float(tags.get("importance") or 0), str(m.get("workspace_id") or ""),
                     len(sources), _json_dumps(sources), float(m.get("created_at") or now),
                     now, "raw"),
                )
                added += 1
        return added

    def count_memory_archive(self, workspace_id="", status=None):
        with self._connect() as conn:
            sql = "SELECT COUNT(*) AS c FROM memory_archive WHERE 1=1"
            args = []
            if workspace_id:
                sql += " AND workspace_id=?"
                args.append(workspace_id)
            if status:
                sql += " AND status=?"
                args.append(status)
            row = conn.execute(sql, args).fetchone()
        return row["c"] if row else 0

    def list_memory_archive(self, workspace_id="", status=None, k=200):
        with self._connect() as conn:
            sql = "SELECT * FROM memory_archive WHERE 1=1"
            args = []
            if workspace_id:
                sql += " AND workspace_id=?"
                args.append(workspace_id)
            if status:
                sql += " AND status=?"
                args.append(status)
            sql += " ORDER BY created_at DESC LIMIT ?"
            args.append(min(k, 1000))
            rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def kb_bias_constraints(self, workspace_id="", k=50):
        """轨 B：bias 知识约束（含 source_memory_id——N4 去重用）；
        返回（知识项列表, 已知识化的记忆 id 集合）。
        隔离：默认取本 workspace 的 bias；空 workspace 视为未授权，不返回全库 bias。
        （bias 为全局约束，跨区共享的受控来源由 ACL/全局 scope 在二期细化；一期先默认本区。）"""
        if not str(workspace_id or "").strip():
            return [], set()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, concept, summary, source_memory_id, workspace_id, updated_at"
                " FROM knowledge_items WHERE library='bias' AND workspace_id=? AND deleted_at IS NULL"
                " ORDER BY id ASC LIMIT ?", (workspace_id, k)).fetchall()
        items = []
        mem_ids = set()
        for r in rows:
            items.append({
                "id": r["id"], "concept": r["concept"], "summary": r["summary"],
                "source_memory_id": r["source_memory_id"], "workspace_id": r["workspace_id"],
                "updated_at": r["updated_at"], "kind": "knowledge",
            })
            if r["source_memory_id"] is not None:
                mem_ids.add(int(r["source_memory_id"]))
        return items, mem_ids


    def search_knowledge(self, query, k=10, workspace_id="", library=None):
        """语义检索 knowledge_items：知识向量 top-k + FTS RRF 融合（v1.1 第 3 步）。"""
        import literature_vectors as V
        vec_hits = V.search(query, k=k)
        fts_ids = []
        with self._connect() as conn:
            try:
                fts_rows = conn.execute(
                    "SELECT rowid FROM knowledge_fts WHERE knowledge_fts MATCH ? LIMIT ?",
                    (query, k * 2),
                ).fetchall()
                fts_ids = [r["rowid"] for r in fts_rows]
            except Exception:
                pass
        RRF_K = 60
        scores = {}
        for rank, (hid, _) in enumerate(vec_hits):
            scores[hid] = scores.get(hid, 0) + 1.0 / (RRF_K + rank + 1)
        for rank, fid in enumerate(fts_ids):
            scores[fid] = scores.get(fid, 0) + 1.0 / (RRF_K + rank + 1)
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:k]
        result_ids = [rid for rid, _ in ranked]
        if not result_ids:
            return []
        with self._connect() as conn:
            placeholders = ",".join("?" * len(result_ids))
            sql = "SELECT * FROM knowledge_items WHERE deleted_at IS NULL AND id IN (" + placeholders + ")"
            args = list(result_ids)
            if workspace_id:
                sql += " AND workspace_id=?"
                args.append(workspace_id)
            if library:
                sql += " AND library=?"
                args.append(library)
            rows = conn.execute(sql, args).fetchall()
        order = {rid: i for i, rid in enumerate(result_ids)}
        results = []
        for r in rows:
            d = dict(r)
            d["rrf_score"] = scores.get(d["id"], 0)
            results.append(d)
        results.sort(key=lambda x: order.get(x["id"], 999))
        return results

    def _add_relation(self, conn, owner_id, rel, workspace_id, now):
        source = rel.get("source")
        target = rel.get("target")
        relation = str(rel.get("relation") or "")
        # 支持 id 对 或 概念名（concept 引用解析为 id）
        source_id = self._resolve_knowledge_ref(conn, owner_id, source, workspace_id)
        target_id = self._resolve_knowledge_ref(conn, owner_id, target, workspace_id)
        if source_id is None or target_id is None:
            raise DomainError("relation source/target must reference existing knowledge items")
        conn.execute(
            "INSERT INTO knowledge_relations (source_id, target_id, relation, workspace_id, updated_at)"
            " VALUES (?,?,?,?,?)",
            (source_id, target_id, relation, workspace_id, now),
        )

    def _resolve_knowledge_ref(self, conn, owner_id, ref, workspace_id):
        """ref 为数字 → 直接 id；否则按 concept 名查找。返回 id 或 None。"""
        if ref is None:
            return None
        if isinstance(ref, (int, float)) and not isinstance(ref, bool):
            row = conn.execute(
                "SELECT id FROM knowledge_items WHERE id=? AND deleted_at IS NULL", (int(ref),),
            ).fetchone()
            return row["id"] if row else None
        name = str(ref).strip()
        if not name:
            return None
        row = conn.execute(
            "SELECT id FROM knowledge_items WHERE workspace_id=? AND deleted_at IS NULL AND concept=?",
            (workspace_id, name),
        ).fetchone()
        return row["id"] if row else None

    def get_knowledge_item(self, kid):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_items WHERE id=? AND deleted_at IS NULL", (int(kid),),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"knowledge item not found: {kid}")
            rels = conn.execute(
                "SELECT source_id, target_id, relation FROM knowledge_relations"
                " WHERE (source_id=? OR target_id=?) AND deleted_at IS NULL",
                (int(kid), int(kid)),
            ).fetchall()
            srcs = conn.execute(
                "SELECT evidence_id FROM evidence_source WHERE knowledge_item_id=? AND deleted_at IS NULL",
                (int(kid),),
            ).fetchall()
            concept_map = {
                r["id"]: r["concept"]
                for r in conn.execute("SELECT id, concept FROM knowledge_items WHERE deleted_at IS NULL")
            }
        d = dict(row)
        d["relations"] = [
            {"source": concept_map.get(r["source_id"], r["source_id"]),
             "target": concept_map.get(r["target_id"], r["target_id"]),
             "source_id": r["source_id"], "target_id": r["target_id"],
             "relation": r["relation"]}
            for r in rels
        ]
        d["sources"] = [s["evidence_id"] for s in srcs]
        return d

    def update_knowledge_item(self, kid, changes):
        allowed = ("concept", "summary", "notes")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_items WHERE id=? AND deleted_at IS NULL", (int(kid),),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"knowledge item not found: {kid}")
            fields = {k: v for k, v in changes.items() if k in allowed}
            workspace_id = row["workspace_id"]
            if fields:
                assignments = [f"{k}=?" for k in fields] + ["updated_at=?"]
                vals = list(fields.values()) + [_now(), int(kid)]
                conn.execute(f"UPDATE knowledge_items SET {', '.join(assignments)} WHERE id=?", vals)
                if "concept" in fields or "summary" in fields:
                    conn.execute("DELETE FROM knowledge_fts WHERE rowid=?", (int(kid),))
                    conn.execute(
                        "INSERT INTO knowledge_fts (rowid, concept, summary) VALUES (?,?,?)",
                        (int(kid), fields.get("concept", row["concept"]),
                         fields.get("summary", row["summary"])),
                    )
            # relations 差量：提供 relations 键则整体替换
            if "relations" in changes:
                now = _now()
                conn.execute(
                    "UPDATE knowledge_relations SET deleted_at=? WHERE source_id=? AND deleted_at IS NULL",
                    (now, int(kid)),
                )
                conn.execute(
                    "UPDATE knowledge_relations SET deleted_at=? WHERE target_id=? AND deleted_at IS NULL",
                    (now, int(kid)),
                )
                for rel in (changes["relations"] or []):
                    self._add_relation(conn, int(kid), rel, workspace_id, now)
            # sources 差量
            if "sources" in changes:
                conn.execute(
                    "UPDATE evidence_source SET deleted_at=? WHERE knowledge_item_id=? AND deleted_at IS NULL",
                    (_now(), int(kid)),
                )
                for eid in (changes["sources"] or []):
                    conn.execute(
                        "INSERT INTO evidence_source (evidence_id, knowledge_item_id, workspace_id, deleted_at)"
                        " VALUES (?,?,?,NULL)",
                        (int(eid), int(kid), workspace_id),
                    )
        return self.get_knowledge_item(kid)

    def soft_delete_knowledge_item(self, kid):
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE knowledge_items SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
                (_now(), _now(), int(kid)),
            )
            if cur.rowcount == 0:
                raise NotFoundError(f"knowledge item not found: {kid}")
            conn.execute("DELETE FROM knowledge_fts WHERE rowid=?", (int(kid),))
        return {"deleted": True, "id": int(kid)}

    # ------------------------------------------------------------ graph

    def graph(self, workspace_id="", library=None):
        """概念网络：nodes = knowledge_items, edges = knowledge_relations（workspace/library 过滤，library 可选）。"""
        with self._connect() as conn:
            node_sql = "SELECT id, concept, library FROM knowledge_items WHERE deleted_at IS NULL"
            node_args = []
            if workspace_id:
                node_sql += " AND workspace_id=?"
                node_args.append(workspace_id)
            if library:
                node_sql += " AND library=?"
                node_args.append(library)
            node_sql += " ORDER BY id"
            nodes = conn.execute(node_sql, node_args).fetchall()
            node_ids = {n["id"] for n in nodes}
            edge_sql = ("SELECT r.source_id, r.target_id, r.relation,"
                        " s.concept AS source_concept, t.concept AS target_concept"
                        " FROM knowledge_relations r"
                        " JOIN knowledge_items s ON s.id=r.source_id AND s.deleted_at IS NULL"
                        " JOIN knowledge_items t ON t.id=r.target_id AND t.deleted_at IS NULL"
                        " WHERE r.deleted_at IS NULL AND r.source_id IN (SELECT id FROM knowledge_items WHERE deleted_at IS NULL")
            edge_args = []
            if workspace_id:
                edge_sql += " AND workspace_id=?"
                edge_args.append(workspace_id)
            if library:
                edge_sql += " AND library=?"
                edge_args.append(library)
            edge_sql += ") AND r.target_id IN (SELECT id FROM knowledge_items WHERE deleted_at IS NULL"
            if workspace_id:
                edge_sql += " AND workspace_id=?"
                edge_args.append(workspace_id)
            if library:
                edge_sql += " AND library=?"
                edge_args.append(library)
            edge_sql += ") ORDER BY r.id"
            edges = conn.execute(edge_sql, edge_args).fetchall()
        return {
            "nodes": [dict(n) for n in nodes],
            "edges": [
                {"source": e["source_id"], "target": e["target_id"],
                 "source_concept": e["source_concept"], "target_concept": e["target_concept"],
                 "relation": e["relation"]}
                for e in edges
            ],
        }

    # ------------------------------------------------------------ dedupe / import / export

    def dedupe_check(self, candidates):
        """DOI/ISBN/标题归一化精确去重。candidates: [{title, doi, isbn}] → 命中列表。"""
        hits = []
        with self._connect() as conn:
            for c in candidates:
                doi = str(c.get("doi") or "").strip().lower()
                isbn = str(c.get("isbn") or "").strip().replace("-", "")
                title = self._normalize_title(str(c.get("title") or ""))
                row = None
                if doi:
                    row = conn.execute(
                        "SELECT id, title, doi FROM documents WHERE deleted_at IS NULL AND lower(doi)=?",
                        (doi,),
                    ).fetchone()
                if row is None and isbn:
                    row = conn.execute(
                        "SELECT id, title, isbn FROM documents WHERE deleted_at IS NULL AND"
                        " replace(isbn,'-','')=?", (isbn,),
                    ).fetchone()
                if row is None and title:
                    rows = conn.execute(
                        "SELECT id, title, doi FROM documents WHERE deleted_at IS NULL"
                    ).fetchall()
                    for r in rows:
                        if self._normalize_title(r["title"]) == title:
                            row = r
                            break
                if row is not None:
                    row_doi = str(row["doi"] or "")
                    hits.append({"candidate": c, "existing_id": row["id"],
                                 "existing_title": row["title"],
                                 "matched_by": "doi" if doi and row_doi.lower() == doi else ("isbn" if isbn else "title")})
        return {"hits": hits, "duplicate_count": len(hits)}

    def _normalize_title(self, title):
        return re.sub(r"\s+", "", title or "").lower()

    def import_bibtex(self, text, workspace_id="", skip_duplicates=True):
        """BibTeX 解析 + 批量导入（DOI/ISBN 命中默认跳过）。返回 imported/skipped。"""
        entries = self._parse_bibtex(text)
        imported, skipped = [], []
        for e in entries:
            check = self.dedupe_check([{"title": e.get("title"), "doi": e.get("doi"), "isbn": e.get("isbn")}])
            if skip_duplicates and check["duplicate_count"]:
                skipped.append({"title": e.get("title"), "reason": "duplicate",
                                "existing_id": check["hits"][0]["existing_id"]})
                continue
            doc = self.create_document({
                "title": e.get("title", ""), "type": "paper", "year": e.get("year"),
                "journal": e.get("journal", ""), "doi": e.get("doi", ""),
                "authors": e.get("authors", []), "tags": ["bibtex"],
                "workspace_id": workspace_id,
            })
            imported.append({"id": doc["id"], "title": doc["title"]})
        return {"imported": imported, "skipped": skipped,
                "imported_count": len(imported), "skipped_count": len(skipped)}

    def _parse_bibtex(self, text):
        entries = []
        # 先按顶层 @type{ 拆分条目，再在每条内解析字段
        starts = [m.start() for m in re.finditer(r"@\w+\s*\{", text)]
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(text)
            chunk = text[start:end]
            hm = re.match(r"@(\w+)\s*\{\s*([^,\s]+)\s*,\s*", chunk)
            if not hm:
                continue
            kind, key = hm.group(1).lower(), hm.group(2).strip()
            body = chunk[hm.end():]
            # 去掉末尾可能残留的 "}"
            body = body.rstrip("}")
            fields = {}
            for fm in re.finditer(r"(\w+)\s*=\s*\{((?:[^{}]|\{[^{}]*\})*)\}", body, re.S):
                fields[fm.group(1).lower()] = fm.group(2).strip()
            authors = []
            if fields.get("author"):
                for a in re.split(r"\s+and\s+", fields["author"]):
                    a = a.strip().strip("{}").strip()
                    if a:
                        authors.append(a)
            try:
                year = int(fields.get("year", "").strip("{}"))
            except (ValueError, TypeError):
                year = None
            entries.append({
                "bibtex_key": key, "kind": kind,
                "title": fields.get("title", "").strip("{}"),
                "authors": authors, "year": year,
                "journal": fields.get("journal", fields.get("booktitle", "")).strip("{}"),
                "doi": fields.get("doi", "").strip("{}"),
                "isbn": fields.get("isbn", "").strip("{}"),
            })
        return entries

    def import_doi(self, doi, workspace_id=""):
        """DOI 元数据导入（Crossref API）。"""
        doi = str(doi or "").strip()
        if not doi:
            raise DomainError("doi is required")
        url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
        req = urllib.request.Request(url, headers={"User-Agent": "dsh-literature/0.2 (mailto:dev@localhost)"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise DomainError(f"crossref fetch failed: {exc}")
        msg = data.get("message", {})
        authors = [
            (a.get("given", "") + " " + a.get("family", "")).strip()
            for a in msg.get("author", [])
        ]
        year = None
        for k in ("published-print", "published-online", "issued"):
            dp = msg.get(k, {}).get("date-parts", [[None]])[0][0]
            if dp:
                year = int(dp)
                break
        doc = self.create_document({
            "title": (msg.get("title") or [""])[0], "type": "paper",
            "authors": authors, "year": year,
            "journal": (msg.get("container-title") or [""])[0],
            "doi": doi, "url": msg.get("URL", ""),
            "tags": ["doi-import"], "workspace_id": workspace_id,
        })
        return doc

    def export_bibtex(self, ids, workspace_id=""):
        entries = []
        with self._connect() as conn:
            for did in ids:
                row = conn.execute(
                    "SELECT * FROM documents WHERE id=? AND workspace_id=? AND deleted_at IS NULL",
                    (int(did), workspace_id),
                ).fetchone()
                if row is None:
                    continue
                d = dict(row)
                authors = _json_loads(d.get("authors_json"))
                entries.append(
                    "@article{" + str(d["id"]) + ",\n"
                    "  title = {" + d["title"] + "},\n"
                    "  author = {" + " and ".join(authors) + "},\n"
                    + (f"  journal = {{{d['journal']}}},\n" if d.get("journal") else "")
                    + (f"  year = {{{d['year']}}},\n" if d.get("year") else "")
                    + (f"  doi = {{{d['doi']}}},\n" if d.get("doi") else "")
                    + "}"
                )
        return "\n\n".join(entries)
