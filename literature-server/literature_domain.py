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
  workspace_id TEXT NOT NULL DEFAULT ''
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
  workspace_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_knowledge_ws ON knowledge_items(workspace_id, deleted_at);

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
                " created_at, updated_at, workspace_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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

    # ------------------------------------------------------------ knowledge

    def create_knowledge_item(self, payload):
        concept = str(payload.get("concept") or "").strip()
        if not concept:
            raise DomainError("concept is required")
        workspace_id = str(payload.get("workspace_id") or "")
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO knowledge_items (concept, summary, notes, created_at, updated_at, workspace_id)"
                " VALUES (?,?,?,?,?,?)",
                (concept, str(payload.get("summary") or ""), str(payload.get("notes") or ""),
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
        return self.get_knowledge_item(kid)

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

    def graph(self, workspace_id=""):
        """概念网络：nodes = knowledge_items, edges = knowledge_relations（workspace 硬过滤）。"""
        with self._connect() as conn:
            nodes = conn.execute(
                "SELECT id, concept FROM knowledge_items WHERE workspace_id=? AND deleted_at IS NULL"
                " ORDER BY id", (workspace_id,),
            ).fetchall()
            edges = conn.execute(
                "SELECT r.source_id, r.target_id, r.relation,"
                " s.concept AS source_concept, t.concept AS target_concept"
                " FROM knowledge_relations r"
                " JOIN knowledge_items s ON s.id=r.source_id AND s.deleted_at IS NULL"
                " JOIN knowledge_items t ON t.id=r.target_id AND t.deleted_at IS NULL"
                " WHERE r.workspace_id=? AND r.deleted_at IS NULL ORDER BY r.id",
                (workspace_id,),
            ).fetchall()
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
