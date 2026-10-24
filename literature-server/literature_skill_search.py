#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""literature_skill_search.py — 技能检索（关键词给人，语义给 agent）。

设计依据：docs/skill-management-v1-design.md

两条路，一份源数据（skill_versions，不可变）：
  关键词路（人）：完全名 > 前缀 > FTS5 bm25 > 标签。**确定性、可解释**。
  语义路（agent）：bge-m3 向量余弦 + apply 成功率 + 新近度。**按意图匹配**。

可见性边界（复用 skills.visibility，不另造字段）：
  visibility='user-only' ⇒ 只出现在人的检索结果里，agent 永远看不到
  visibility='model'     ⇒ 两边都可见（但要 active 且未删除）

三道防「全注入」闸：
  1. semantic_search 只返回 L0（≤MAX_L0 字），**永不返回正文**
  2. k 服务端夹断到 [1, MAX_K]
  3. L2 正文必须显式 layer='l2' 才给，并记录 layer 供质量分析
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import time

MAX_K = 8                 # agent 单次检索上限（服务端夹断，不信调用方）
DEFAULT_K = 5
MAX_L0_CHARS = 120        # 返回给 agent 的单条摘要上限
EMBED_MODEL_NAME = os.environ.get("LITERATURE_EMBED_API_MODEL") or "bge-m3"

# FTS 检索时把这些词当分隔符切分（避免用户输入被当成 FTS 语法）
_FTS_TOKEN = re.compile(r"[0-9A-Za-z_\u4e00-\u9fff]+")


# ---------------------------------------------------------------- 工具
def _j(s, default=None):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {} if default is None else default


def _tags_of(conn, skill_id):
    try:
        return [r[0] for r in conn.execute(
            "SELECT tag FROM skill_tags WHERE skill_id=? ORDER BY tag", (skill_id,))]
    except sqlite3.OperationalError:
        return []


def embed_text_for(name, category, tags, l0, l1):
    """参与嵌入的文本。顺序固定（便于算 hash 判断是否需要重嵌）。

    不嵌 L2 正文：语义检索找的是「这技能干什么」，不是「正文里有啥词」。
    """
    return " | ".join([
        str(name or "").strip(),
        str(category or "").strip(),
        ",".join(sorted(tags or [])),
        " ".join(str(l0 or "").split()),
        " ".join(str(l1 or "").split()),
    ]).strip(" |")


def text_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _fts_terms(q):
    """把用户输入切成安全 token（防止 FTS5 把 . ( ) " 当语法 → syntax error）。

    这条是血泪教训：之前 `?q=<DOI>` 直接把 FTS5 打挂（syntax error near "."）。
    """
    return _FTS_TOKEN.findall(str(q or ""))


def _fts_query(q):
    """构造 FTS5 trigram 查询。trigram 要求 ≥3 字符，更短的交给 LIKE 兜底。"""
    q = " ".join(str(q or "").split())
    if len(q) < 3:
        return ""
    # 整串加引号做短语匹配（trigram 支持子串）；长串再按词拆 OR 提高召回
    terms = [t for t in _fts_terms(q) if len(t) >= 3]
    if not terms:
        return ""
    return " OR ".join('"%s"' % t for t in terms)



def _row_l0_and_meta(conn, version_id):
    row = conn.execute("""
        SELECT v.id, v.skill_id, v.version, v.summary_l0, v.overview_l1, v.skill_md,
               s.slug, s.title, s.description, s.category_id, s.visibility,
               s.lifecycle, s.scope, s.workspace_id, s.active_version_id, s.deleted_at
          FROM skill_versions v JOIN skills s ON s.id = v.skill_id
         WHERE v.id = ?""", (int(version_id),)).fetchone()
    return row


# ---------------------------------------------------------------- 索引维护
def sync_version(conn, version_id, *, touch_tags=True):
    """把一个版本同步进 FTS 索引，并把向量标脏。返回状态 dict。

    FTS 用「先删后插」保证幂等（普通 FTS5 表没有 UPSERT）。
    """
    row = _row_l0_and_meta(conn, version_id)
    if not row:
        return {"ok": False, "reason": "version not found", "version_id": version_id}
    (vid, skill_id, ver, l0, l1, md, slug, title, desc, cat_id,
     vis, lifecycle, scope, ws, active_vid, deleted) = row

    tags = _tags_of(conn, skill_id) if touch_tags else []
    category = ""
    if cat_id is not None:
        try:
            r = conn.execute("SELECT name FROM categories WHERE id=?", (int(cat_id),)).fetchone()
            category = (r[0] if r else "") or ""
        except sqlite3.OperationalError:
            category = ""

    # ① FTS：先删同版本行，再插入
    conn.execute("DELETE FROM skill_search_fts WHERE skill_version_id = ?", (vid,))
    conn.execute(
        "INSERT INTO skill_search_fts (skill_version_id, name, summary_l0, overview_l1, tags, category)"
        " VALUES (?,?,?,?,?,?)",
        (vid, " ".join([str(slug or ""), str(title or "")]).strip(),
         l0 or "", l1 or "", " ".join(tags), category))

    # ② 向量：算 text_hash，变了就标 stale（不在此处做嵌入，避免写事务里调网络）
    text = embed_text_for(title or slug, category, tags, l0, l1)
    th = text_hash(text)
    cur = conn.execute("SELECT text_hash, status FROM skill_vectors WHERE skill_version_id=?", (vid,)).fetchone()
    if cur is None:
        conn.execute("INSERT INTO skill_vectors (skill_version_id, text_hash, status) VALUES (?,?,'pending')",
                     (vid, th))
        vec_status = "pending"
    elif cur[0] != th:
        conn.execute("UPDATE skill_vectors SET text_hash=?, status='stale' WHERE skill_version_id=?",
                     (th, vid))
        vec_status = "stale"
    else:
        vec_status = cur[1]
    return {"ok": True, "version_id": vid, "fts": "ok", "vector": vec_status,
            "text_hash": th, "tags": tags, "category": category}


def rebuild_all(conn, *, only_active=True):
    """全量重建 FTS（幂等）。返回处理条数。"""
    q = """SELECT v.id FROM skill_versions v JOIN skills s ON s.id=v.skill_id
            WHERE s.deleted_at IS NULL"""
    if only_active:
        q += " AND s.lifecycle IN ('active','draft')"
    ids = [r[0] for r in conn.execute(q)]
    conn.execute("DELETE FROM skill_search_fts")
    n = 0
    for vid in ids:
        r = sync_version(conn, vid)
        if r.get("ok"):
            n += 1
    conn.commit()
    return {"rebuilt": n, "total_versions": len(ids)}


# ---------------------------------------------------------------- 嵌入（纯 stdlib，不依赖 numpy/faiss）
_EMBED_PROVIDER = (os.environ.get("LITERATURE_EMBED_PROVIDER") or "local").strip().lower()
_EMBED_API_BASE = (os.environ.get("LITERATURE_EMBED_API_BASE") or "").rstrip("/")
_EMBED_API_MODEL = os.environ.get("LITERATURE_EMBED_API_MODEL") or ""
_EMBED_API_KEY = os.environ.get("LITERATURE_EMBED_API_KEY") or "local-noauth"
_EMBED_BATCH = max(1, int(os.environ.get("LITERATURE_EMBED_API_BATCH") or 32))


def _l2norm(vec):
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def embed_texts(texts):
    """文本 → L2 归一化向量（list[list[float]]）。

    刻意不复用 literature_vectors：那个模块顶层 import faiss/numpy，
    而技能嵌入只需要一次 HTTP 调用。解耦之后技能检索能在最小 Python 环境跑。
    provider=api  → OpenAI 兼容 /v1/embeddings
    provider=local → 才回落到 literature_vectors（需要 faiss）
    """
    if not texts:
        return []
    if _EMBED_PROVIDER != "api":
        try:
            import literature_vectors as V      # 懒加载：只有 local 模式才需要 faiss
        except ImportError as exc:
            raise RuntimeError(
                "LITERATURE_EMBED_PROVIDER=%s 需要 faiss/numpy，当前解释器没有（%s）；"
                "要么设 LITERATURE_EMBED_PROVIDER=api 走 HTTP embedding，要么用装了 faiss 的解释器"
                % (_EMBED_PROVIDER, exc)) from None
        return [[float(x) for x in v] for v in V.embed_texts(texts)]

    if not _EMBED_API_BASE or not _EMBED_API_MODEL:
        raise RuntimeError("provider=api 需要 LITERATURE_EMBED_API_BASE 与 LITERATURE_EMBED_API_MODEL")

    import urllib.request
    out = []
    for start in range(0, len(texts), _EMBED_BATCH):
        chunk = texts[start:start + _EMBED_BATCH]
        body = json.dumps({"model": _EMBED_API_MODEL, "input": chunk}).encode("utf-8")
        req = urllib.request.Request(
            _EMBED_API_BASE + "/embeddings", data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + _EMBED_API_KEY})
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        items = sorted(payload.get("data") or [], key=lambda x: x.get("index", 0))
        if len(items) != len(chunk):
            raise RuntimeError("embedding 返回条数不符：期望 %d 实际 %d" % (len(chunk), len(items)))
        out.extend(_l2norm([float(v) for v in it["embedding"]]) for it in items)
    return out


def _strip_frontmatter(md):
    """去掉 SKILL.md 的 YAML frontmatter，返回正文。"""
    t = (md or "").lstrip()
    if t.startswith("---"):
        end = t.find("\n---", 3)
        if end > 0:
            t = t[end + 4:]
    return " ".join(t.split())


def _pack(vec):
    return struct.pack("<%df" % len(vec), *vec)


def _unpack(blob):
    n = len(blob) // 4
    return struct.unpack("<%df" % n, blob)


def embed_pending(conn, *, limit=64, dry_run=False):
    """把 pending/stale 的版本嵌入。失败写 status='failed' + error，不静默。

    联网调用在事务外做：先在内存里算好，再一次性写回。
    """
    rows = list(conn.execute(
        "SELECT v.id, v.summary_l0, v.overview_l1, s.slug, s.title, s.category_id, v.skill_id"
        "  FROM skill_versions v JOIN skills s ON s.id=v.skill_id"
        "  LEFT JOIN skill_vectors sv ON sv.skill_version_id = v.id"
        " WHERE s.deleted_at IS NULL"
        "   AND (sv.skill_version_id IS NULL OR sv.status IN ('pending','stale','failed'))"
        " LIMIT ?", (int(limit),)))
    if not rows:
        return {"embedded": 0, "failed": 0, "remaining": 0}
    if dry_run:
        return {"embedded": 0, "would": len(rows), "dry_run": True}

    texts, meta = [], []
    for vid, l0, l1, slug, title, cat_id, skill_id in rows:
        tags = _tags_of(conn, skill_id)
        category = ""
        if cat_id is not None:
            try:
                r = conn.execute("SELECT name FROM categories WHERE id=?", (int(cat_id),)).fetchone()
                category = (r[0] if r else "") or ""
            except sqlite3.OperationalError:
                pass
        texts.append(embed_text_for(title or slug, category, tags, l0, l1))
        meta.append((vid, text_hash(texts[-1])))

    try:
        vecs = embed_texts(texts)
    except Exception as exc:
        # 整批失败：全部标 failed，保留原因（不能静默）
        now = time.time()
        for vid, th in meta:
            conn.execute("UPDATE skill_vectors SET status='failed', error=?, text_hash=?, built_at=?"
                         " WHERE skill_version_id=?", (str(exc)[:400], th, now, vid))
        conn.commit()
        return {"embedded": 0, "failed": len(meta), "error": str(exc)[:200]}

    now = time.time()
    ok = 0
    for (vid, th), vec in zip(meta, vecs):
        try:
            arr = [float(x) for x in vec]
            conn.execute("""INSERT INTO skill_vectors (skill_version_id, model, dim, vec, text_hash, status, error, built_at)
                            VALUES (?,?,?,?,?,'ok','',?)
                            ON CONFLICT(skill_version_id) DO UPDATE SET
                              model=excluded.model, dim=excluded.dim, vec=excluded.vec,
                              text_hash=excluded.text_hash, status='ok', error='', built_at=excluded.built_at""",
                         (vid, EMBED_MODEL_NAME, len(arr), _pack(arr), th, now))
            ok += 1
        except Exception as exc:
            conn.execute("UPDATE skill_vectors SET status='failed', error=? WHERE skill_version_id=?",
                         (str(exc)[:400], vid))
    conn.commit()
    remaining = conn.execute(
        "SELECT COUNT(*) FROM skill_vectors WHERE status IN ('pending','stale','failed')").fetchone()[0]
    return {"embedded": ok, "failed": len(meta) - ok, "remaining": remaining}


# ---------------------------------------------------------------- 人：关键词
def keyword_search(conn, q, *, tag=None, category=None, lifecycle=None,
                   workspace_id=None, include_user_only=True, limit=50):
    """人的检索：确定性排序。返回 L0 列表（不返回正文）。

    排序档位（越小越靠前）：
      0 = 名称完全等于
      1 = 名称前缀
      2 = FTS5 bm25 命中
      3 = 仅有标签命中
    同档位内按 90 天 apply 次数降序、更新时间降序。
    """
    q = str(q or "").strip()
    limit = max(1, min(int(limit or 50), 200))
    # 取候选：active_version 或最新版本
    sql = """
      SELECT s.id, s.slug, s.title, s.description, s.visibility, s.lifecycle,
             s.scope, s.workspace_id, s.updated_at,
             COALESCE(s.active_version_id,
                      (SELECT id FROM skill_versions v WHERE v.skill_id=s.id ORDER BY v.version DESC LIMIT 1)) AS vid
        FROM skills s
       WHERE s.deleted_at IS NULL"""
    args = []
    if lifecycle:
        sql += " AND s.lifecycle = ?"
        args.append(lifecycle)
    if workspace_id:
        sql += " AND (s.scope='global' OR s.workspace_id = ?)"
        args.append(workspace_id)
    if not include_user_only:
        sql += " AND s.visibility = 'model'"
    rows = [dict(zip(("skill_id", "slug", "title", "description", "visibility",
                      "lifecycle", "scope", "workspace_id", "updated_at", "vid"), r))
            for r in conn.execute(sql, args)]

    if not rows:
        return []

    tag_set = set()
    if tag:
        tag_set = {r[0] for r in conn.execute("SELECT skill_id FROM skill_tags WHERE tag=?", (tag,))}

    # 短查询（<3 字符）trigram 覆盖不到 ⇒ LIKE 兜底；中文单字/双字很常见，不能漏
    like_hits = set()
    if q and len(q) < 3:
        pat = "%" + q.replace("%", "").replace("_", "") + "%"
        for r in conn.execute("""
                SELECT s.slug FROM skills s
                  LEFT JOIN skill_versions v ON v.skill_id = s.id
                 WHERE s.deleted_at IS NULL
                   AND (s.slug LIKE ? OR s.title LIKE ? OR s.description LIKE ?
                        OR IFNULL(v.summary_l0,'') LIKE ? OR IFNULL(v.overview_l1,'') LIKE ?)""",
                              (pat, pat, pat, pat, pat)):
            like_hits.add(r[0])

    # FTS 候选：query 为空时不算
    fts_score = {}
    if q:
        fq = _fts_query(q)
        if fq:
            try:
                for vid, bm in conn.execute(
                        "SELECT skill_version_id, bm25(skill_search_fts) FROM skill_search_fts"
                        " WHERE skill_search_fts MATCH ? LIMIT 500", (fq,)):
                    fts_score[int(vid)] = float(bm)
            except sqlite3.OperationalError:
                fts_score = {}     # FTS 挂了也不能让整个检索 500

    # 90 天 apply 次数
    since = time.time() - 90 * 86400
    applies = {}
    try:
        for sid, n in conn.execute(
                "SELECT skill_id, COUNT(*) FROM skill_usage_events"
                " WHERE event_kind='apply' AND occurred_at >= ? GROUP BY skill_id", (since,)):
            applies[sid] = n
    except sqlite3.OperationalError:
        pass

    ql = q.lower()
    out = []
    for r in rows:
        if tag_set and r["skill_id"] not in tag_set:
            continue
        name = (r["slug"] or "").lower()
        title = (r["title"] or "").lower()
        if not q:
            tier = 2
        elif ql == name or ql == title:
            tier = 0
        elif name.startswith(ql) or title.startswith(ql):
            tier = 1
        elif r["vid"] in fts_score:
            tier = 2
        elif r["slug"] in like_hits or tag_set:
            tier = 3
        else:
            continue          # 有 query 但没命中 ⇒ 不返回（确定性：不猜）
        out.append({
            "skill_id": r["skill_id"], "name": r["slug"], "title": r["title"],
            "l0": _l0_of(conn, r["vid"]), "description": r["description"],
            "visibility": r["visibility"], "lifecycle": r["lifecycle"],
            "scope": r["scope"], "workspace_id": r["workspace_id"],
            "version_id": r["vid"],
            "tier": tier,
            "bm25": round(fts_score.get(r["vid"], 0.0), 4),
            "apply_90d": applies.get(r["skill_id"], 0),
            "updated_at": r["updated_at"],
        })

    out.sort(key=lambda x: (x["tier"], -x["apply_90d"], -(x["updated_at"] or 0)))
    return out[:limit]


def _l0_of(conn, version_id):
    if not version_id:
        return ""
    r = conn.execute("SELECT summary_l0 FROM skill_versions WHERE id=?", (int(version_id),)).fetchone()
    return " ".join((r[0] if r else "").split())[:MAX_L0_CHARS]


# ---------------------------------------------------------------- agent：语义
def semantic_search(conn, query, *, k=DEFAULT_K, tag=None):
    """agent 的检索：只返回 L0，k 服务端夹断。

    只看 visibility='model' 且 lifecycle='active' 的技能 —— 边界不靠调用方自觉。
    """
    k = max(1, min(int(k or DEFAULT_K), MAX_K))
    q = " ".join(str(query or "").split())
    if not q:
        return {"results": [], "reason": "empty query"}

    cands = []
    for vid, sid, slug, title, l0, vec, vis, lc in conn.execute("""
            SELECT v.id, s.id, s.slug, s.title, v.summary_l0, sv.vec, s.visibility, s.lifecycle
              FROM skill_vectors sv
              JOIN skill_versions v ON v.id = sv.skill_version_id
              JOIN skills s ON s.id = v.skill_id
             WHERE sv.status = 'ok' AND sv.vec IS NOT NULL
               AND s.deleted_at IS NULL
               AND s.visibility = 'model'
               AND s.lifecycle = 'active'"""):
        cands.append((vid, sid, slug, title, l0, vec))

    if not cands:
        return {"results": [], "reason": "no embedded model-visible skills"}

    if tag:
        keep = {r[0] for r in conn.execute("SELECT skill_id FROM skill_tags WHERE tag=?", (tag,))}
        cands = [c for c in cands if c[1] in keep]
        if not cands:
            return {"results": [], "reason": "no skill matches tag"}

    qvec = embed_texts([q])[0]
    qv = [float(x) for x in qvec]

    since = time.time() - 90 * 86400
    apply_n, total_n = {}, {}
    try:
        for sid, kind, n in conn.execute(
                "SELECT skill_id, event_kind, COUNT(*) FROM skill_usage_events"
                " WHERE occurred_at >= ? GROUP BY skill_id, event_kind", (since,)):
            (apply_n if kind == "apply" else total_n)[sid] = n
    except sqlite3.OperationalError:
        pass

    scored = []
    for vid, sid, slug, title, l0, blob in cands:
        try:
            dv = _unpack(blob)
        except Exception:
            continue
        if len(dv) != len(qv):
            continue
        dot = sum(a * b for a, b in zip(qv, dv))     # 两边都已 L2 归一化 ⇒ 点积=余弦
        loads = total_n.get(sid, 0)
        succ = (apply_n.get(sid, 0) / loads) if loads else 0.0
        score = 0.75 * dot + 0.15 * succ + 0.10 * (1.0 if loads else 0.0)
        scored.append({
            "name": slug, "title": title,
            "l0": " ".join((l0 or "").split())[:MAX_L0_CHARS],
            "score": round(score, 4),
            "similarity": round(dot, 4),
            "apply_rate": round(succ, 3),
            "version_id": vid,
        })
    scored.sort(key=lambda x: -x["score"])
    return {"results": scored[:k], "k": k, "candidates": len(cands)}


# ---------------------------------------------------------------- 加载
def load_skill(conn, name, *, layer="l1", workspace_id=None):
    """按名字加载技能。默认 L1，L2 必须显式。

    agent 侧调用：只允许 visibility='model' + lifecycle='active'。
    """
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    layer = (layer or "l1").lower()
    if layer not in ("l0", "l1", "l2"):
        return {"ok": False, "error": "layer must be l0|l1|l2"}

    row = conn.execute("""
        SELECT s.id, s.slug, s.title, s.visibility, s.lifecycle, s.scope, s.workspace_id,
               COALESCE(s.active_version_id,
                        (SELECT id FROM skill_versions v WHERE v.skill_id=s.id ORDER BY v.version DESC LIMIT 1)) AS vid
          FROM skills s
         WHERE s.deleted_at IS NULL AND (s.slug = ? OR s.title = ?)
         LIMIT 1""", (name, name)).fetchone()
    if not row:
        return {"ok": False, "error": "skill not found: %s" % name}
    sid, slug, title, vis, lc, scope, ws, vid = row
    if vis != "model" or lc != "active":
        return {"ok": False, "error": "skill not model-invocable: %s (visibility=%s, lifecycle=%s)"
                                      % (name, vis, lc)}
    if workspace_id and scope == "workspace" and ws and ws != workspace_id:
        return {"ok": False, "error": "skill belongs to another workspace"}

    v = conn.execute("SELECT id, version, summary_l0, overview_l1, skill_md FROM skill_versions WHERE id=?",
                     (int(vid),)).fetchone()
    if not v:
        return {"ok": False, "error": "skill has no version"}
    vid, ver, l0, l1, md = v
    content = {"l0": l0 or "", "l1": l1 or "", "l2": md or ""}[layer]
    if layer in ("l1", "l2") and not content.strip():
        # L1/L2 没生成时不要给空内容：降级到 L0；L0 也没有就给去掉 frontmatter 的正文摘要。
        # 不能把 YAML 头直接喂给模型——那是元数据，不是可执行指令。
        fallback = (l0 or "").strip() or _strip_frontmatter(md)[:800]
        return {"ok": True, "name": slug, "title": title, "version": ver,
                "layer": "l0" if (l0 or "").strip() else "raw",
                "content": fallback, "chars": len(fallback),
                "degraded": True,
                "note": ("%s 尚未生成，已降级；要全文请用 layer='l2'" % layer)}
    return {"ok": True, "name": slug, "title": title, "version": ver,
            "layer": layer, "content": content, "chars": len(content or "")}
