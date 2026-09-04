#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_nightly.py — literature 夜间加工管线（v1.1 第 2 步）

时机：凌晨 03:30（deepmemory 03:00 错峰；由 systemd timer 调度，Persistent=true 跨天补跑）
模型：deepseek-v4-flash-0731（谷价；fallback 链 → deepseek-v4-flash），经 uuapi 网关
流程：读文献(documents) → LLM 拆证据(claim+原文摘录+锚点) → LLM 提炼知识(单一性) → 向量化入库 → 关联
产出：evidence（doc_id+锚点，无锚点不入库）/ knowledge_items（library 默认 runtime，bias 不可归档）
"""

import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from literature_domain import LiteratumStore, DomainError, install_schema  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "literature.db")
CREDENTIALS = ["/www/dsh/home/.credentials.yaml"]


def _credentials_map():
    for cand in CREDENTIALS:
        if os.path.isfile(cand):
            try:
                import yaml as _yaml
                doc = _yaml.safe_load(open(cand, encoding="utf-8"))
                return (doc.get("refs") or doc) or {}
            except Exception:
                continue
    return {}


def llm_chat(prompt, model=None, system=None, api_key=None):
    """uuapi 网关 deepseek-v4-flash-0731，fallback 链。返回 {"content":...} 或 {"error":...}。"""
    model = model or "deepseek-v4-flash-0731"
    creds = _credentials_map()
    key = api_key or creds.get("UUAPI_API_KEY") or creds.get("UUAPI_GPT_API_KEY") or ""
    if not key:
        return {"error": "no api key (refs.UUAPI_API_KEY)"}
    url = "https://uuapi.io/v1/chat/completions"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = {"model": model, "messages": messages, "max_tokens": 1024, "temperature": 0.2}
    chain = []
    if model:
        chain.append(model)
    for m in ("deepseek-v4-flash", "deepseek-v4-flash-0731"):
        if m not in chain:
            chain.append(m)
    last_err = None
    for m in chain:
        body["model"] = m
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={
                "Authorization": "Bearer " + key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if content:
                return {"content": content, "model": m}
            return {"error": "empty response"}
        except Exception as exc:
            last_err = str(exc)[:200]
    return {"error": last_err or "all models failed"}


def extract_json(text):
    """从 LLM 输出提取 JSON（容忍 markdown 围栏）。"""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
        s = s.strip()
    try:
        return json.loads(s)
    except Exception:
        # 尝试截取首个 [ 或 { 到末尾
        for start_ch, end_ch in (("[", "]"), ("{", "}")):
            a, b = s.find(start_ch), s.rfind(end_ch)
            if a >= 0 and b > a:
                try:
                    return json.loads(s[a:b + 1])
                except Exception:
                    continue
    return None


def process_document(store, doc):
    """单篇文献：LLM 拆证据 + 提炼知识 → 入库。"""
    doc_id = doc["id"]
    workspace_id = doc["workspace_id"] or ""
    title = doc["title"] or ""
    text = doc.get("full_text") or ""
    if not text.strip():
        return {"doc_id": doc_id, "skipped": "no text"}

    # 1) 拆证据
    res = llm_chat(
        "以下是文献内容。请拆出其中的论证性主张（evidence），每条约含 claim(主张)、"
        "evidence_text(原文摘录,必须能在原文定位)、chapter_anchor(章节/段落标识,如无则空)、"
        "stance(supporting/contradicting/contextual)。\n"
        "要求：evidence_text 必须是原文逐字摘录；无明确来源位置的主张不要输出；返回 JSON 数组。\n"
        "文献标题：" + title + "\n文献内容：" + text[:4000],
        system="你是文献证据提取器：只输出 JSON 数组，不要解释。每条 {\"claim\":\"\",\"evidence_text\":\"\",\"chapter_anchor\":\"\",\"stance\":\"\"}",
    )
    if res.get("error"):
        return {"doc_id": doc_id, "error": res["error"]}
    items = extract_json(res.get("content", ""))
    if not isinstance(items, list):
        items = []
    ev_ids = []
    for it in items[:10]:
        claim = str(it.get("claim") or "").strip()
        ev_text = str(it.get("evidence_text") or "").strip()
        anchor = str(it.get("chapter_anchor") or "").strip()
        if not claim or not ev_text:
            continue
        # 无锚点证据不入库（v1.1：锚点可定位是硬要求）
        try:
            ev = store.create_evidence({
                "claim": claim, "evidence_text": ev_text,
                "chapter_anchor": anchor, "doc_id": doc_id,
                "stance": it.get("stance") if it.get("stance") in ("supporting", "contradicting", "contextual") else "contextual",
                "workspace_id": workspace_id,
            })
            ev_ids.append(ev["id"])
        except DomainError:
            continue
    return {"doc_id": doc_id, "evidence_added": len(ev_ids), "evidence_ids": ev_ids}


def process_evidence_to_knowledge(store, ev):
    """单条证据：LLM 提炼知识（单一性：一条一件事）。"""
    claim = ev["claim"]
    ev_text = (ev["evidence_text"] or "")[:500]
    workspace_id = ev["workspace_id"] or ""
    res = llm_chat(
        "从以下证据提炼一条知识。要求：concept(概念名,简洁)、summary(一句话结论,单一性=只讲一件事)、"
        "不重复原文、不含立场词。返回 JSON。\n"
        "证据主张：" + claim + "\n原文摘录：" + ev_text,
        system="你是知识提炼器：只输出 JSON {\"concept\":\"\",\"summary\":\"\"}，不要解释。",
    )
    if res.get("error"):
        return {"evidence_id": ev["id"], "error": res["error"]}
    obj = extract_json(res.get("content", ""))
    if not isinstance(obj, dict):
        return {"evidence_id": ev["id"], "skipped": "bad json"}
    concept = str(obj.get("concept") or "").strip()
    summary = str(obj.get("summary") or "").strip()
    if not concept or not summary:
        return {"evidence_id": ev["id"], "skipped": "empty fields"}
    try:
        kn = store.create_knowledge_item({
            "concept": concept, "summary": summary,
            "workspace_id": workspace_id,
            "library": "runtime",  # 加工默认 runtime；bias 不在此产生
            "sources": [ev["id"]],
        })
        return {"evidence_id": ev["id"], "knowledge_id": kn["id"]}
    except DomainError as exc:
        return {"evidence_id": ev["id"], "error": str(exc)}


def process_archive_to_knowledge(store, archive_row):
    """单条 deepmemory 原料归档 → LLM 提炼知识。status=raw→processed。"""
    memory_id = archive_row["memory_id"]
    summary = archive_row["summary"] or ""
    sources = archive_row["sources_json"] or "[]"
    try:
        sources = json.loads(sources)
    except Exception:
        sources = []
    src_text = "\n".join(str(s.get("content") or "") for s in sources[:5])
    workspace_id = archive_row["workspace_id"] or ""
    res = llm_chat(
        "从以下记忆原料提炼一条知识。要求：concept(概念名,简洁)、summary(一句话结论,单一性=只讲一件事)、"
        "不重复原文。返回 JSON。\n记忆摘要：" + summary + "\n原始对话摘录：" + (src_text[:1500] or "无"),
        system="你是知识提炼器：只输出 JSON {\"concept\":\"\",\"summary\":\"\"}，不要解释。",
    )
    if res.get("error"):
        return {"memory_id": memory_id, "error": res["error"], "staged": False}
    obj = extract_json(res.get("content", ""))
    if not isinstance(obj, dict):
        return {"memory_id": memory_id, "skipped": "bad json", "staged": False}
    concept = str(obj.get("concept") or "").strip()
    summary_k = str(obj.get("summary") or "").strip()
    if not concept or not summary_k:
        return {"memory_id": memory_id, "skipped": "empty fields", "staged": False}
    try:
        kn = store.create_knowledge_item({
            "concept": concept, "summary": summary_k,
            "workspace_id": workspace_id,
            "library": archive_row.get("library") or "runtime",
            "source_memory_id": memory_id,  # 溯源链：knowledge → memory_archive(memory_id)
        })
        # 标记归档已加工
        with store._connect() as conn:
            conn.execute("UPDATE memory_archive SET status='processed' WHERE memory_id=?", (int(memory_id),))
        return {"memory_id": memory_id, "knowledge_id": kn["id"], "staged": True}
    except DomainError as exc:
        return {"memory_id": memory_id, "error": str(exc), "staged": False}


def process_archive_batch(store, workspace_id="", limit=50):
    """raw 归档 → processed（提炼 knowledge）。返回统计。"""
    with store._connect() as conn:
        sql = "SELECT * FROM memory_archive WHERE status='raw'"
        args = []
        if workspace_id:
            sql += " AND workspace_id=?"
            args.append(workspace_id)
        sql += " ORDER BY id LIMIT ?"
        args.append(limit)
        rows = conn.execute(sql, args).fetchall()
    n = 0
    for row in rows:
        r = process_archive_to_knowledge(store, dict(row))
        if r.get("staged"):
            n += 1
        elif r.get("error"):
            print("  archive#%s: %s" % (r.get("memory_id"), r.get("error")), file=sys.stderr)
    return n


def run_once(store=None, doc_limit=20, dry_run=False):
    """一次夜间加工：全部文献 → 证据 → 知识。返回统计。"""
    store = store or LiteratumStore(DB_PATH)
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM documents"
            " WHERE deleted_at IS NULL AND lifecycle_status='active'"
            " AND full_text != '' ORDER BY id DESC LIMIT ?",
            (doc_limit,),
        ).fetchall()
    docs = [dict(r) for r in rows]
    out = {"documents": len(docs), "evidence_added": 0, "knowledge_added": 0, "per_doc": []}
    if dry_run:
        return out
    for doc in docs:
        r = process_document(store, doc)
        out["per_doc"].append(r)
        out["evidence_added"] += r.get("evidence_added", 0)
    # 证据 → 知识
    with store._connect() as conn:
        evs = conn.execute(
            "SELECT * FROM evidence WHERE deleted_at IS NULL AND doc_id IS NOT NULL"
            " AND id NOT IN (SELECT evidence_id FROM evidence_source) ORDER BY id LIMIT ?",
            (doc_limit * 5,),
        ).fetchall()
    for ev in evs:
        r = process_evidence_to_knowledge(store, dict(ev))
        if r.get("knowledge_id"):
            out["knowledge_added"] += 1
    # 归档层加工：memory_archive raw → knowledge（v0.3 专属对接主通道）
    arch_added = process_archive_batch(store, workspace_id="deepseek-harness", limit=doc_limit)
    out["archive_processed"] = arch_added
    out["knowledge_added"] += arch_added
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="literature 夜间加工管线")
    ap.add_argument("--dry-run", action="store_true", help="只统计不加工")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    result = run_once(doc_limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
