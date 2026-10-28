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
from literature_domain import LiteratumStore, table_columns
import literature_vectors as V

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "literature.db")
TOP_K = 4          # 每条知识找前 4 相近
# 阈值：0.45 时平均 11 边/节点，图会糊成毛球；实测 0.65 约 3.7 边/节点，岛群才分得开。
SIM_THRESHOLD = float(os.environ.get("LITERATURE_REL_THRESHOLD") or 0.65)
# 同工作区约束：图谱按 workspace 过滤，跨区的边两端不在同一张图里，建了也看不见。
SAME_WORKSPACE = (os.environ.get("LITERATURE_REL_SAME_WS") or "1") != "0"
SAME_LIB_BONUS = 0.05  # 同库加成（同库更易聚岛）
RELATION = "相关"

# P2b：边元数据（口径见 RELATION_VOCAB.md。kNN 相似边 = 提示而非断言 ⇒ directed=0，无 origin）
PROVENANCE = "similarity"
CONFIDENCE = 0.5
DIRECTED = 0
META_COLUMNS = ("provenance", "confidence", "directed")


def run(dry_run=False, workspace_id=""):
    store = LiteratumStore(DB_PATH)
    with store._connect() as conn:
        sql = "SELECT id, concept, library, workspace_id FROM knowledge_items WHERE deleted_at IS NULL"
        args = []
        if workspace_id:
            sql += " AND workspace_id=?"
            args.append(workspace_id)
        rows = conn.execute(sql, args).fetchall()
        # P2b：元数据列存在性检测（老库无 provenance/confidence/directed → 降级为旧 5 列 INSERT）
        has_meta = set(META_COLUMNS) <= table_columns(conn, "knowledge_relations")
    ids = [r["id"] for r in rows]
    lib = {r["id"]: r["library"] for r in rows}
    ws = {r["id"]: r["workspace_id"] for r in rows}   # 每条知识自身的归属（不写死）
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
            if SAME_WORKSPACE and (ws.get(tid) or "") != (ws.get(kid) or ""):
                continue  # 跨工作区的边在图里两端不同图，建了也看不见
            # 同库加成
            eff = score + (SAME_LIB_BONUS if lib.get(tid) == lib.get(kid) else 0)
            if eff < SIM_THRESHOLD:
                skip += 1
                continue
            if dry_run:
                added += 1        # 只计数，不写库（修 P1-9：原来 --dry-run 照样写）
                continue
            with store._connect() as conn:
                exists = conn.execute(
                    "SELECT id FROM knowledge_relations WHERE source_id=? AND target_id=? AND relation=? AND deleted_at IS NULL",
                    (kid, tid, RELATION)).fetchone()
                if exists:
                    continue
                if has_meta:
                    conn.execute(
                        "INSERT INTO knowledge_relations (source_id, target_id, relation, workspace_id,"
                        " provenance, confidence, directed, updated_at)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (kid, tid, RELATION, ws.get(kid, ""), PROVENANCE, CONFIDENCE, DIRECTED, now))
                else:  # 未迁移的库：退回旧 5 列写入（边仍建成，仅无元数据列）
                    conn.execute(
                        "INSERT INTO knowledge_relations (source_id, target_id, relation, workspace_id, updated_at)"
                        " VALUES (?,?,?,?,?)", (kid, tid, RELATION, ws.get(kid, ""), now))
                added += 1
    print(f"建关系边: {added} 条（跳过低于阈值 {skip} 次；元数据列 {'有' if has_meta else '无→降级'}）")
    return added


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="用向量相似度为知识建关系边")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库")
    ap.add_argument("--workspace", default="", help="只处理指定 workspace（空=全部）")
    ap.add_argument("--threshold", type=float, default=None, help="相似度阈值（默认 0.65）")
    a = ap.parse_args()
    if a.threshold is not None:
        SIM_THRESHOLD = a.threshold
    print("  参数: threshold=%.2f  same_workspace=%s  workspace=%s  dry_run=%s"
          % (SIM_THRESHOLD, SAME_WORKSPACE, a.workspace or "(全部)", a.dry_run))
    n = run(dry_run=a.dry_run, workspace_id=a.workspace)
    print("完成: %s %d 条关系边" % ("将新增" if a.dry_run else "新增", n))
