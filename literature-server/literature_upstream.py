#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_upstream.py — deepmemory 上游访问共享层（单服务合并后供 6260 使用）

从原 kb-server 抽出：readonly 调 deepmemory（search/libraries/list/graph）。
MEMORY_URL / MEMORY_TOKEN_FILE 由 unit env 注入（生产 6230 / 测试 6240）。
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
MEMORY_URL = os.environ.get("LITERATURE_MEMORY_URL", "http://127.0.0.1:6230")
MEMORY_TOKEN_FILE = os.environ.get("LITERATURE_MEMORY_API_TOKEN_FILE",
                                   os.path.join(DATA_DIR, "memory-api-token"))
TIMEOUT = float(os.environ.get("LITERATURE_UPSTREAM_TIMEOUT", "10"))
DEFAULT_WORKSPACE = os.environ.get("LITERATURE_DEFAULT_WORKSPACE", "deepseek-harness")


def read_memory_token():
    """上游 deepmemory token（只读通道；全权 token，单机回环下可接受）。"""
    for path in (MEMORY_TOKEN_FILE,
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
    token = read_memory_token()
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
    except Exception as exc:
        return 503, {"error": f"upstream unreachable: {exc}"}


def list_memories(workspace_id):
    """枚举某 workspace 全部 active 记忆（list 端点，不走语义召回）。"""
    st, data = upstream("GET",
                        f"/v1/memories/list?workspace_id={urllib.parse.quote(workspace_id)}&status=active&limit=1000")
    if st != 200:
        return st, []
    return st, data.get("memories", [])
