#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_ingest.py — deepmemory export-archive → literature 原料归档层 ingest（v0.3 第 1 步）

数据流：deepmemory(export-archive, since 增量, 脱敏原文) → POST /archive-ingest → memory_archive 表
        →（夜间由 literature_nightly 加工成 knowledge → 向量）
属性：
  · 只读拉 deepmemory（export-archive），不改 deepmemory
  · since 增量：默认拉最近 N 天，落库按 memory_id 幂等去重
  · 归档存脱敏原文（sources）+ 溯源锚点（memory_id）
"""

import argparse
import json
import os
import sys
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEEP_MEMORY = os.environ.get("LITERATURE_MEMORY_URL", "http://127.0.0.1:6230")
DEEP_TOKEN_FILE = os.environ.get("LITERATURE_MEMORY_API_TOKEN_FILE",
                                 os.path.join(BASE_DIR, "data", "memory-api-token"))
LIT_URL = os.environ.get("LITERATURE_LIT_URL", "http://127.0.0.1:6260")
LIT_TOKEN_FILE = os.environ.get("LITERATURE_API_TOKEN_FILE", os.path.join(BASE_DIR, "data", "api-token"))


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _http(method, url, body=None, token=None, timeout=60):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, json.JSONDecodeError):
            return exc.code, {"error": f"HTTP {exc.code}"}
    except Exception as exc:
        return 503, {"error": str(exc)}


def fetch_deepmemory_archive(since, workspace_id, limit=200):
    """拉 deepmemory export-archive 增量。返回 [(memory dict)]。"""
    dt = _read(DEEP_TOKEN_FILE)
    url = (DEEP_MEMORY + "/v1/memories/export-archive?since=" + str(int(since))
           + ("&workspace_id=" + workspace_id if workspace_id else "")
           + "&limit=" + str(limit))
    st, data = _http("GET", url, token=dt)
    if st != 200:
        print(f"deepmemory export-archive HTTP {st}: {data}", file=sys.stderr)
        return []
    return data.get("memories", [])


def ingest_to_literature(memories):
    """POST /archive-ingest 到本库。返回 ingested 数。"""
    if not memories:
        return 0
    lt = _read(LIT_TOKEN_FILE)
    st, data = _http("POST", LIT_URL + "/v1/literature/archive-ingest",
                     body={"memories": memories}, token=lt)
    if st != 200 and "ingested" not in data:
        print(f"literature archive-ingest HTTP {st}: {data}", file=sys.stderr)
        return 0
    return int(data.get("ingested") or 0)


def run_once(since_days=1, workspace_id="", limit=500, dry_run=False):
    """拉 deepmemory 归档 → literature 原料层。
    workspace_id 默认空 = 拉全部工作区（每条记忆自带 workspace_id，归档后各自归属）。
    历史 bug：曾默认 "deepseek-harness"（假工作区），导致只拉/写进孤儿库。"""
    now = time.time()
    since = now - since_days * 86400
    mems = fetch_deepmemory_archive(since, workspace_id, limit)
    print(f"deepmemory export-archive 拉取 {len(mems)} 条（since={since_days}天, ws={workspace_id or '全部'}）")
    if dry_run:
        return len(mems)
    add = ingest_to_literature(mems)
    print(f"ingest 新增 {add} 条到 memory_archive（去重后）")
    return add


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="deepmemory export-archive → literature 原料归档 ingest")
    ap.add_argument("--since-days", type=float, default=1, help="拉最近 N 天增量")
    ap.add_argument("--workspace-id", default="",
                    help="限定工作区（默认空=全部工作区，各条按自身 workspace_id 归属）")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    n = run_once(since_days=args.since_days, workspace_id=args.workspace_id,
                 limit=args.limit, dry_run=args.dry_run)
    print(f"完成: {n} 条")
