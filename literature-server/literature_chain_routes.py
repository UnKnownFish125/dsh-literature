#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""认识演进链路由（阶段 3.1）—— 输出形状对齐前端 client.js 的 ChainCard 契约。

端点：
  GET /v1/literature/chains             全部链（默认：有证据的）
  GET /v1/literature/chains?status=open 按状态过滤
  GET /v1/literature/chains/<chain_id>  单条
  GET /v1/literature/propositions       49 条命题的正反证据统计（给矩阵视图用）

数据源两级 fallback：
  ① 生产库 lit_prop_evidence / lit_propositions（阶段 2 落库后自动生效）
  ② 冻结文件 /tmp/p28/verified_labels.json + /tmp/p30/assertions_v2.json

前端契约字段（来自 client.js ChainCard）：
  chain_id, topic, scope_note, data_provenance,
  from_belief{assertion_id,statement,status,polarity,year,year_note,evidence_source},
  to_belief{assertion_id,statement,status,polarity},
  transitions[]{strength,source_group,doc,year,journal,role,title,quote,title_source,anchor},
  evidence_summary{distinct_independent_sources,total,strong,weak,invalid,scope,note},
  source_groups[], independent_sources, condition_branches[], aligned_support[],
  next_beliefs[], caveats[], generation{} / pipeline{}
"""
import json
import os
import sqlite3
import time

_DATA_DIR = os.environ.get("LITERATURE_DATA_DIR") or \
    "/www/dsh-literature-deploy/literature-server/data"
PROD_DB = os.environ.get("LITERATURE_DB") or os.path.join(_DATA_DIR, "literature.db")
FROZEN = "/tmp/p28/verified_labels.json"
ASSERTIONS = "/tmp/p30/assertions_v2.json"
AUDIT = "/tmp/p28/assertion_condition_audit.json"
PAIRS = "/tmp/p28/chain_pairs.json"

ACCEPTED = ("supports", "refutes", "qualifies")
_CACHE = {"at": 0, "data": None, "props": None}
_TTL = 5.0


# ---------------------------------------------------------------- 元数据
def _load_assertion_meta():
    meta = {}
    try:
        d = json.load(open(ASSERTIONS, encoding="utf-8"))
    except Exception:
        return meta
    for a in (d.get("preserved_assertions") or []) + (d.get("assertions") or []):
        aid = a.get("id")
        if isinstance(aid, int):
            aid = "a#%d" % aid
        meta[aid] = {
            "canonical": a.get("canonical") or "",
            "branch": a.get("branch") or a.get("family") or "?",
            "polarity": a.get("polarity"),
            "judge_mode": a.get("judge_mode") or "conditional",
        }
    try:
        au = json.load(open(AUDIT, encoding="utf-8"))
        items = au if isinstance(au, list) else (au.get("assertions") or au.get("items") or [])
        for it in items:
            aid = it.get("id")
            if isinstance(aid, int):
                aid = "a#%d" % aid
            if aid in meta and it.get("rewritten_canonical"):
                meta[aid]["canonical"] = it["rewritten_canonical"]
    except Exception:
        pass
    return meta


def _doc_meta():
    out = {}
    try:
        c = sqlite3.connect("file:%s?mode=ro" % PROD_DB, uri=True)
        for i, t, y, j, w in c.execute(
                "SELECT id, title, year, journal, workspace_id FROM documents "
                "WHERE deleted_at IS NULL"):
            out[i] = {"title": t or "", "year": y, "journal": j or "", "workspace_id": w or ""}
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- 证据装载
def _load_rows():
    """返回 [(prop_key, doc_id, verdict, quote, reason, model)]"""
    try:
        c = sqlite3.connect("file:%s?mode=ro" % PROD_DB, uri=True)
        has = c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name='lit_prop_evidence'").fetchone()
        if has:
            n = c.execute("SELECT COUNT(*) FROM lit_prop_evidence").fetchone()[0]
            if n:
                return list(c.execute("""
                    SELECT p.prop_key, e.document_id, e.verdict, e.quote, e.reason, e.judged_by
                      FROM lit_prop_evidence e
                      JOIN lit_propositions p ON p.id = e.proposition_id
                     WHERE e.frozen = 1""")), "db"
    except Exception:
        pass
    try:
        lab = json.load(open(FROZEN, encoding="utf-8"))
    except Exception:
        return None, "none"
    rows = [(l.get("proposition_id"), l.get("doc_id"), l.get("verdict"),
             l.get("evidence_verbatim"), l.get("reason"), l.get("judged_by"))
            for l in (lab.get("labels") or [])]
    return rows, "frozen"


def _clean_quote(q):
    if not q:
        return ""
    try:
        arr = json.loads(q) if str(q).strip().startswith("[") else None
    except Exception:
        arr = None
    txt = " ".join(str(x) for x in arr if x) if isinstance(arr, list) else str(q)
    return " ".join(txt.split())[:600]


def _strength_of(verdict, quote):
    """strong=直接反驳/支持；weak=限定；invalid=未涉及或残句（不计入独立来源）。"""
    if verdict in ("supports", "refutes"):
        return "strong"
    if verdict == "qualifies":
        return "weak"
    return "invalid"


def _role_of(verdict):
    return {"supports": "supports", "refutes": "refutes", "qualifies": "qualifies"}.get(verdict, "")


# ---------------------------------------------------------------- 装配
def _build_props():
    """49 条命题 → {prop_key: {support:[], refute:[], qualifies:[], na, corrupt}}"""
    rows, src = _load_rows()
    meta = _load_assertion_meta()
    docs = _doc_meta()
    props = {}
    for pk in meta:
        props[pk] = {"support": [], "refute": [], "qualifies": [],
                     "not_addressed": 0, "found_corrupt": 0}
    for pk, doc_id, verdict, quote, reason, model in rows:
        p = props.setdefault(pk, {"support": [], "refute": [], "qualifies": [],
                                  "not_addressed": 0, "found_corrupt": 0})
        if verdict in ("supports", "refutes", "qualifies") and doc_id is not None:
            dm = docs.get(doc_id, {})
            p[{"supports": "support", "refutes": "refute",
               "qualifies": "qualifies"}[verdict]].append({
                   "doc_id": doc_id,
                   "doc": "doc#%d" % doc_id,
                   "source_group": "doc#%d" % doc_id,   # 一篇论文 = 一个来源组
                   "title": dm.get("title", ""),
                   "year": dm.get("year"),
                   "journal": dm.get("journal", ""),
                   "quote": _clean_quote(quote),
                   "reason": (reason or "")[:220],
                   "role": _role_of(verdict),
                   "strength": _strength_of(verdict, quote),
                   "title_source": "documents 表（DB）",
               })
        elif verdict == "not_addressed":
            p["not_addressed"] += 1
        elif verdict == "found_corrupt":
            p["found_corrupt"] += 1
    for pk, p in props.items():
        p["distinct_support"] = len({x["doc_id"] for x in p["support"]})
        p["distinct_refute"] = len({x["doc_id"] for x in p["refute"]})
        if p["distinct_support"] and p["distinct_refute"]:
            p["status"] = "disputed"
        elif p["distinct_support"] >= 2:
            p["status"] = "consensus"
        elif p["distinct_support"] + p["distinct_refute"] + len(p["qualifies"]):
            p["status"] = "single"
        else:
            p["status"] = "gap"
    return props, meta, src


def _belief(meta, pk, *, status, year_note=""):
    m = meta.get(pk, {})
    return {
        "assertion_id": pk,
        "statement": m.get("canonical", ""),
        "status": status,
        "polarity": m.get("polarity"),
        "year": None,                      # 文献未给出旧认识的年份 ⇒ 不臆造
        "year_note": year_note or "原始来源未给出年份（不臆造）",
        "evidence_source": "reported_prior_belief" if status == "superseded" else "",
    }


def _chain_from_pair(pair, props, meta):
    fk, tk = pair.get("from"), pair.get("to")
    fp = props.get(fk) or {}
    tp = props.get(tk) or {}
    # transitions：旧认识被反驳的证据 + 新认识被支持的证据
    trans = []
    for x in (fp.get("refute") or []):
        trans.append(dict(x, role="refutes"))
    for x in (fp.get("support") or []):
        trans.append(dict(x, role="supports"))
    if tk:
        for x in (tp.get("support") or []):
            trans.append(dict(x, role="supports"))
        for x in (tp.get("refute") or []):
            trans.append(dict(x, role="refutes"))
    if not tk:
        for x in (fp.get("qualifies") or []):
            trans.append(dict(x, role="qualifies"))
    # 去重（同一 doc 同一 quote 只保留一次），优先保留 refutes
    seen, uniq = set(), []
    for x in sorted(trans, key=lambda y: 0 if y.get("role") == "refutes" else 1):
        k = (x.get("doc_id"), (x.get("quote") or "")[:80])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
    groups = sorted({x["source_group"] for x in uniq if x.get("strength") != "invalid"})
    strong = sum(1 for x in uniq if x.get("strength") == "strong")
    weak = sum(1 for x in uniq if x.get("strength") == "weak")
    invalid = sum(1 for x in uniq if x.get("strength") == "invalid")
    # 状态
    if tk and fp.get("distinct_refute"):
        state = "superseded"
    elif fp.get("status") == "disputed" or tp.get("status") == "disputed":
        state = "open"
    elif tp.get("status") == "consensus":
        state = "current"
    else:
        state = "open"
    return {
        "chain_id": pair.get("chain_id"),
        "topic": pair.get("topic") or (meta.get(fk) or {}).get("canonical", "")[:40],
        "scope_note": pair.get("scope_note", ""),
        "data_provenance": {
            "titles_source": "documents 表（DB），非模型生成",
            "corrected_at": None,
            "note": "标题/年份/期刊均来自 DB；引用为论文原文逐字片段",
        },
        "from_belief": _belief(meta, fk, status="superseded" if fp.get("distinct_refute") else "open"),
        "to_belief": _belief(meta, tk, status="current") if tk else {
            "assertion_id": "", "statement": "（该命题尚无公认的新认识）",
            "status": "open", "polarity": None},
        "transitions": uniq,
        "evidence_summary": {
            "distinct_independent_sources": len(groups),
            "total": len(uniq),
            "strong": strong, "weak": weak, "invalid": invalid,
            "scope": "基于 17 篇文本可用文献的逐篇判定（库内共 20 篇；doc#3 与本领域无关、doc#18/#22 文本质量差，未纳入）",
            "note": "独立来源按 doc 去重；invalid（未涉及/残句）不计入",
        },
        "source_groups": groups,
        "independent_sources": len(groups),
        "condition_branches": [],
        "aligned_support": [],
        "next_beliefs": [],
        "caveats": pair.get("caveats") or [],
        "generation": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M"),
            "rule_version": "p28-matrix-v2",
            "model": "deepseek-flash",
            "temperature": 0,
            "verified_note": "Lead 已复核 3 格（a#2×doc#7/doc#10 改判）",
            "scope_note": "18 篇已抽取 × 49 条命题 = 833 个逐篇判定",
        },
        "status": state,
        "proposition_ids": [x for x in (fk, tk) if x],
    }


def _chain_from_single(pk, props, meta):
    p = props.get(pk) or {}
    trans = []
    for role, key in (("refutes", "refute"), ("supports", "support"), ("qualifies", "qualifies")):
        for x in (p.get(key) or []):
            trans.append(dict(x, role=role))
    groups = sorted({x["source_group"] for x in trans if x.get("strength") != "invalid"})
    return {
        "chain_id": pk,
        "topic": (meta.get(pk) or {}).get("canonical", "")[:56],
        "scope_note": "",
        "data_provenance": {"titles_source": "documents 表（DB）", "corrected_at": None,
                            "note": "引用为论文原文逐字片段"},
        "from_belief": _belief(meta, pk, status="open"),
        "to_belief": {"assertion_id": "", "statement": "（尚未形成公认新认识；正反证据并列）",
                      "status": "open", "polarity": None},
        "transitions": trans,
        "evidence_summary": {
            "distinct_independent_sources": len(groups),
            "total": len(trans),
            "strong": sum(1 for x in trans if x.get("strength") == "strong"),
            "weak": sum(1 for x in trans if x.get("strength") == "weak"),
            "invalid": sum(1 for x in trans if x.get("strength") == "invalid"),
            "scope": "基于 17 篇文本可用文献的逐篇判定",
            "note": "独立来源按 doc 去重",
        },
        "source_groups": groups,
        "independent_sources": len(groups),
        "condition_branches": [], "aligned_support": [], "next_beliefs": [],
        "caveats": [],
        "generation": {"generated_at": time.strftime("%Y-%m-%d %H:%M"),
                       "rule_version": "p28-matrix-v2", "model": "deepseek-flash",
                       "temperature": 0},
        "status": p.get("status", "gap"),
        "proposition_ids": [pk],
    }


def _experiment_verdicts():
    """读实验裁决（表不存在或为空时返回 {}）。"""
    out = {}
    try:
        c = sqlite3.connect("file:%s?mode=ro" % PROD_DB, uri=True)
        has = c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name='lit_experiment_verdicts'").fetchone()
        if not has:
            return out
        for pk, vid, verdict, cond, meas, note, at, by, st in c.execute("""
                SELECT p.prop_key, v.id, v.verdict, v.conditions_json, v.measured_json,
                       v.evidence_note, v.performed_at, v.performed_by, v.status
                  FROM lit_experiment_verdicts v
                  JOIN lit_propositions p ON p.id = v.proposition_id
                 WHERE v.status != 'retracted'
                 ORDER BY v.created_at DESC"""):
            out.setdefault(pk, []).append({
                "id": vid, "verdict": verdict,
                "conditions": _pj(cond), "measured": _pj(meas),
                "note": note, "performed_at": at, "performed_by": by, "status": st,
            })
    except Exception:
        pass
    return out


def _pj(s, default=None):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {} if default is None else default


def _build(workspace_id=""):
    """返回 (chains, props)。workspace_id 非空时只统计该工作区下的文献。"""
    now = time.time()
    ck = workspace_id or "*"
    if _CACHE.get("ws") == ck and _CACHE.get("data") and now - _CACHE["at"] < _TTL:
        return _CACHE["data"], _CACHE["props"]
    props_all, meta, src = _build_props()
    if not meta:
        return None, None
    if workspace_id:
        docs = _doc_meta()
        keep = {i for i, d in docs.items() if d.get("workspace_id") == workspace_id}
        props = {}
        for pk, p in props_all.items():
            q = {"support": [], "refute": [], "qualifies": [],
                 "not_addressed": p["not_addressed"], "found_corrupt": p["found_corrupt"]}
            for key in ("support", "refute", "qualifies"):
                q[key] = [x for x in p[key] if x["doc_id"] in keep]
            q["distinct_support"] = len({x["doc_id"] for x in q["support"]})
            q["distinct_refute"] = len({x["doc_id"] for x in q["refute"]})
            if q["distinct_support"] and q["distinct_refute"]:
                q["status"] = "disputed"
            elif q["distinct_support"] >= 2:
                q["status"] = "consensus"
            elif q["distinct_support"] + q["distinct_refute"] + len(q["qualifies"]):
                q["status"] = "single"
            else:
                q["status"] = "gap"
            props[pk] = q
    else:
        props = props_all
    chains = []
    used = set()
    try:
        pairs = (json.load(open(PAIRS, encoding="utf-8")) or {}).get("chains") or []
    except Exception:
        pairs = []
    for pair in pairs:
        ch = _chain_from_pair(pair, props, meta)
        if not ch.get("transitions"):
            continue        # 该工作区下这对命题没有任何证据 ⇒ 不出这条链
        chains.append(ch)
        used.update(x for x in (pair.get("from"), pair.get("to")) if x)
    # 其余有证据的命题按单命题链输出
    for pk, p in props.items():
        if pk in used:
            continue
        if p["status"] == "gap":
            continue
        chains.append(_chain_from_single(pk, props, meta))
    exps = _experiment_verdicts()
    # 有实验裁决但文献零证据的命题，也要出链（你的实验本身就是一条认识）
    emitted = set()
    for ch in chains:
        emitted.update(ch.get("proposition_ids") or [])
    for pk in exps:
        if pk in emitted or pk not in props:
            continue
        ch = _chain_from_single(pk, props, meta)
        chains.append(ch)
        emitted.add(pk)
    for ch in chains:
        hits = []
        for pk in ch.get("proposition_ids") or []:
            hits.extend(exps.get(pk) or [])
        ch["experiment_verdicts"] = hits
        if hits:
            ch["status"] = "experiment_settled" if any(
                h.get("status") == "confirmed" for h in hits) else ch.get("status")
    order = {"experiment_settled": -1, "disputed": 0, "open": 1, "superseded": 2,
             "current": 3, "single": 4, "consensus": 5, "gap": 6}
    chains.sort(key=lambda c: (order.get(c.get("status"), 9), -c["independent_sources"]))
    _CACHE.update(at=now, data=chains, props=props, ws=ck)
    return chains, props


# ---------------------------------------------------------------- 路由
def try_handle(handler, method, parts, qs, body=None):
    if len(parts) < 3 or parts[0] != "v1" or parts[1] != "literature":
        return False
    head = parts[2]
    if head not in ("chains", "propositions"):
        return False
    if method != "GET":
        handler._send(405, {"error": "method not allowed"})
        return True
    try:
        wsid = (qs.get("workspace_id", [""])[0] or "").strip()
        chains, props = _build(wsid)
        if chains is None:
            handler._send(200, {"chains": [], "total": 0, "source": "none",
                                "message": "尚无命题数据（阶段 2 未落库且冻结文件不可读）"})
            return True

        if head == "propositions":
            meta = _load_assertion_meta()
            out = []
            for pk, p in props.items():
                m = meta.get(pk) or {}
                out.append({"proposition_id": pk, "status": p["status"],
                            "canonical": m.get("canonical", ""),
                            "branch": m.get("branch", "?"),
                            "polarity": m.get("polarity"),
                            "judge_mode": m.get("judge_mode", "conditional"),
                            "support": p["distinct_support"], "refute": p["distinct_refute"],
                            "qualifies": len(p["qualifies"]),
                            "not_addressed": p["not_addressed"],
                            "found_corrupt": p["found_corrupt"]})
            out.sort(key=lambda x: int(x["proposition_id"].split("#")[1]))
            handler._send(200, {"propositions": out, "total": len(out)})
            return True

        # 单条链
        if len(parts) >= 4:
            key = parts[3]
            for ch in chains:
                if ch["chain_id"] == key or key in ch.get("proposition_ids", []):
                    handler._send(200, {"chain": ch})
                    return True
            handler._send(404, {"error": "chain not found", "key": key})
            return True

        status = (qs.get("status", [""])[0] or "").strip()
        sel = [c for c in chains if not status or c.get("status") == status]
        counts = {}
        for c in chains:
            counts[c.get("status")] = counts.get(c.get("status"), 0) + 1
        handler._send(200, {
            "chains": sel, "total": len(sel), "counts": counts,
            "source": "db-or-frozen",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        return True
    except Exception as exc:
        handler._send(500, {"error": str(exc), "kind": type(exc).__name__})
        return True
