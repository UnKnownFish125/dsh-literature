#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_vectors.py — literature 自有知识向量引擎（v1.1 第 1 步）

与 deepmemory 记忆 FAISS **完全独立**：
  · 模型：jinaai/jina-embeddings-v2-base-zh（fastembed 本地推理，768 维，中文优化）
  · 索引：data/knowledge.faiss（IndexFlatIP + IndexIDMap）
  · 缓存：统一缓存路径 env LITERATURE_FASTEMBED_CACHE（jina 三份缓存归一）

用途：knowledge_items 加工入库时向量化；kb_query 语义检索 = 知识向量 top-k + FTS RRF。
"""

import json
import os
import threading

import faiss
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
KNOWLEDGE_INDEX_PATH = os.path.join(DATA_DIR, "knowledge.faiss")
DIM_PATH = os.path.join(DATA_DIR, "dim.json")

# 向量维度（jina-embeddings-v2-base-zh = 768）
KNOWLEDGE_DIM = 768

# 统一 fastembed 缓存路径（v1.1：jina 三份缓存归一——统一指向已验证的 /opt/AstrBot/fastembed_cache）
FASTEMBED_CACHE = os.environ.get(
    "LITERATURE_FASTEMBED_CACHE",
    "/opt/AstrBot/fastembed_cache",
)

# ── embedding provider 配置（新增：api = OpenAI 兼容 /v1/embeddings）─────────
# local（默认）= fastembed jina-embeddings-v2-base-zh；api = 本机 llama.cpp bge-m3 等
EMBED_PROVIDER = os.environ.get("LITERATURE_EMBED_PROVIDER", "local").strip().lower()
EMBED_API_BASE = os.environ.get("LITERATURE_EMBED_API_BASE", "").rstrip("/")
EMBED_API_MODEL = os.environ.get("LITERATURE_EMBED_API_MODEL", "")
EMBED_API_KEY = os.environ.get("LITERATURE_EMBED_API_KEY", "")
try:
    EMBED_API_BATCH = max(1, int(os.environ.get("LITERATURE_EMBED_API_BATCH", "32")))
except ValueError:
    EMBED_API_BATCH = 32

_lock = threading.Lock()
_embed_model = None
_index = None
_index_loaded = False


def _load_embed_model():
    global _embed_model
    with _lock:
        if _embed_model is None:
            from fastembed import TextEmbedding
            _embed_model = TextEmbedding(
                model_name="jinaai/jina-embeddings-v2-base-zh",
                cache_dir=FASTEMBED_CACHE,
            )
    return _embed_model


def _write_dim(dim=None):
    with open(DIM_PATH, "w", encoding="utf-8") as fh:
        json.dump({"dim": int(dim or KNOWLEDGE_DIM)}, fh)


def _l2_normalize(vecs):
    """L2 归一化（IndexFlatIP 下等价余弦）；零向量保持原样。"""
    out = []
    for v in vecs:
        a = np.asarray(v, dtype=np.float32)
        n = float(np.linalg.norm(a))
        out.append(a / n if n > 1e-12 else a)
    return out


def _embed_api(texts):
    """OpenAI 兼容 /v1/embeddings（provider=api）。分批发送，避免单请求过大。"""
    import urllib.request

    if not EMBED_API_BASE or not EMBED_API_MODEL:
        raise RuntimeError("LITERATURE_EMBED_PROVIDER=api 需要 LITERATURE_EMBED_API_BASE 与 LITERATURE_EMBED_API_MODEL")
    key = EMBED_API_KEY or "local-noauth"
    out = []
    total = len(texts)
    for start in range(0, total, EMBED_API_BATCH):
        chunk = texts[start:start + EMBED_API_BATCH]
        body = json.dumps({"model": EMBED_API_MODEL, "input": chunk}).encode("utf-8")
        req = urllib.request.Request(
            EMBED_API_BASE + "/embeddings",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "embedding API 第 %d 批失败（offset=%d, size=%d, total=%d）: %s"
                % (start // EMBED_API_BATCH + 1, start, len(chunk), total, e)
            ) from e
        items = sorted(payload.get("data") or [], key=lambda x: x.get("index", 0))
        if len(items) != len(chunk):
            raise RuntimeError("embedding API 返回条数不符：期望 %d，实际 %d（offset=%d）" % (len(chunk), len(items), start))
        out.extend(np.asarray(it["embedding"], dtype=np.float32) for it in items)
    if not out:
        raise RuntimeError("embedding API 返回空结果")
    return out


def embed_texts(texts):
    """文本 → 归一化向量（list[np.ndarray float32]）。"""
    if not texts:
        return []
    if EMBED_PROVIDER == "api":
        raw = _embed_api([str(t) for t in texts])
    else:
        model = _load_embed_model()
        raw = [np.asarray(v, dtype=np.float32) for v in model.embed([str(t) for t in texts])]
    return _l2_normalize(raw)
def _ensure_index(dim=None):
    global _index, _index_loaded
    dim = dim or KNOWLEDGE_DIM
    with _lock:
        if _index is not None:
            return _index
        if not _index_loaded and os.path.exists(KNOWLEDGE_INDEX_PATH):
            try:
                _index = faiss.read_index(KNOWLEDGE_INDEX_PATH)
                _index_loaded = True
                return _index
            except Exception:
                pass  # 损坏则重建
        _index = faiss.IndexIDMap(faiss.IndexFlatIP(dim))
        _index_loaded = True
        _write_dim(dim)
    return _index


def add_vectors(ids, vectors):
    """批量添加 (id, vec) 到知识索引。幂等：id 已存在则跳过（调用方负责去重）。"""
    if not ids or not vectors:
        return 0
    idx = _ensure_index(dim=len(vectors[0]))
    mat = np.vstack([np.asarray(v, dtype=np.float32).reshape(1, -1) for v in vectors])
    ids_arr = np.asarray([int(i) for i in ids], dtype=np.int64)
    idx.add_with_ids(mat, ids_arr)
    _save()
    return len(ids)


def remove_ids(ids):
    """删除 ids（faiss remove）。"""
    if not ids:
        return 0
    idx = _ensure_index()
    try:
        idx.remove_ids(np.asarray([int(i) for i in ids], dtype=np.int64))
        _save()
    except Exception:
        pass
    return len(ids)


def search(query_text, k=10, exclude_ids=None):
    """语义检索：query → top-k (id, score)。返回 [(id, score)]。"""
    if not query_text or not str(query_text).strip():
        return []
    vec = embed_texts([query_text])
    if not vec:
        return []
    idx = _ensure_index()
    if idx.ntotal == 0:
        return []
    mat = np.asarray(vec[0], dtype=np.float32).reshape(1, -1)
    scores, ids = idx.search(mat, min(k * 2, idx.ntotal))
    results = []
    for s, i in zip(scores[0], ids[0]):
        if i < 0:
            continue
        if exclude_ids and int(i) in exclude_ids:
            continue
        results.append((int(i), float(s)))
        if len(results) >= k:
            break
    return results


def rebuild(ids_texts):
    """全量重建索引。ids_texts: [(id, text), ...] → 清空后重建。"""
    global _index, _index_loaded
    if not ids_texts:
        idx = faiss.IndexIDMap(faiss.IndexFlatIP(KNOWLEDGE_DIM))
        _index = idx
        _index_loaded = True
        _save()
        return 0
    texts = [t for _, t in ids_texts]
    vectors = embed_texts(texts)
    idx = faiss.IndexIDMap(faiss.IndexFlatIP(len(vectors[0]) if vectors else KNOWLEDGE_DIM))
    ids_arr = np.asarray([int(i) for i, _ in ids_texts], dtype=np.int64)
    if vectors:
        mat = np.vstack([np.asarray(v, dtype=np.float32).reshape(1, -1) for v in vectors])
        idx.add_with_ids(mat, ids_arr)
    _index = idx
    _index_loaded = True
    _write_dim(idx.d)
    _save()
    return len(ids_texts)


def total():
    idx = _ensure_index()
    return idx.ntotal


def _save():
    idx = _ensure_index()
    faiss.write_index(idx, KNOWLEDGE_INDEX_PATH)
