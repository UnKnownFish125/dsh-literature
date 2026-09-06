#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_relations.py — 用向量相似度自动为知识建关系边（岛群状图谱的数据基础，B 关系聚簇）

对每条知识，用 FAISS 向量找语义最相近的若干条（超过阈值的视为"相近关系"），建立
knowledge_relations 边。同库/同主题优先。这样图谱的"岛"有真实的连线（相近知识聚簇）。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from literature_domain import LiteratumStore
import literature_vectors as V

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "literature.db")
TOP_K = 4          # 每条知识找前 4 相近
SIM_THRESHOLD = 0.45   # 余弦相似度阈值：低于则不连边（防噪声）
SAME_LIB_BONUS = 0.05  # 同库加成（同库更易聚岛）
RELATION = "相关"


def run(dry_run=False):
    store = LiteratumStore(DB_PATH)
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT id, concept, library FROM knowledge_items WHERE deleted_at IS NULL").fetchall()
    ids = [r["id"] for r in rows]
    lib = {r["id"]: r["library"] for r in rows}
    concept = {r["id"]: r["concept"] for r in rows}
    print(f"知识 {len(ids)} 条，开始向量建关系...")

    added = 0
    skip = 0
    now = time.time()
    # 向量索引里 id 对应的向量相似度 —— 逐条查询
    for kid in ids:
        try:
            near = V.search(concept[kid], k=TOP_K + 1, exclude_ids=[kid])
        except Exception as e:
            print(f"  #{kid} 向量查询失败: {e}")
            continue
        for tid, score in near:
            if tid == kid or tid not in lib:
                continue  # 跳过自身和不在活跃知识表的 id（防外键约束失败）
            # 同库加成
            eff = score + (SAME_LIB_BONUS if lib.get(tid) == lib.get(kid) else 0)
            if eff < SIM_THRESHOLD:
                skip += 1
                continue
            with store._connect() as conn:
                exists = conn.execute(
                    "SELECT id FROM knowledge_relations WHERE source_id=? AND target_id=? AND relation=? AND deleted_at IS NULL",
                    (kid, tid, RELATION)).fetchone()
                if exists:
                    continue
                conn.execute(
                    "INSERT INTO knowledge_relations (source_id, target_id, relation, workspace_id, updated_at)"
                    " VALUES (?,?,?,?,?)", (kid, tid, RELATION, "deepseek-harness", now))
                added += 1
    print(f"建关系边: {added} 条（跳过低于阈值 {skip} 次）")
    return added


if __name__ == "__main__":
    n = run(dry_run="--dry-run" in sys.argv)
    print(f"完成: 新增 {n} 条关系边")
