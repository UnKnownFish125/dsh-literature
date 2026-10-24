#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验裁决路由（阶段 2 的配套：让"我的实验能标记哪一方成立"真正可用）。

设计立场（来自用户原话）：
    「论文这种，得拿实际说事，记录正反方向的观点，如果我实验出来，
      就能标记谁是正的了。」

所以：文献层只记录观点分布，**裁决权在实验**。本模块是实验裁决的唯一写入口。

端点：
  GET  /v1/literature/experiments                    列出裁决（可按命题过滤）
  GET  /v1/literature/experiments/<proposition_id>   某命题的裁决
  POST /v1/literature/experiments                    记录一条裁决
  PATCH /v1/literature/experiments/<id>              改状态（proposed→confirmed/retracted）

POST 体：
  {
    "proposition_id": "a#3",            # 必需，也可以传 "a#3" 或 "3"
    "verdict": "support_side",          # 必需: support_side|refute_side|neither|inconclusive
    "conditions": {"material":"Ti2SnC","temperature":"..."},   # 实验条件
    "measured":   {"note":"...","values":[...]},               # 实测数据
    "evidence_note": "为什么这样裁",     # 必需
    "attachments": ["/path/to/fig.png"],
    "performed_by": "lazyfish"
  }
"""
import json
import os
import sqlite3
import time

_DATA_DIR = os.environ.get("LITERATURE_DATA_DIR") or \
    "/www/dsh-literature-deploy/literature-server/data"
PROD_DB = os.environ.get("LITERATURE_DB") or os.path.join(_DATA_DIR, "literature.db")
VERDICTS = ("support_side", "refute_side", "neither", "inconclusive")
STATUSES = ("proposed", "confirmed", "retracted")


def _conn():
    return sqlite3.connect(PROD_DB, timeout=15)


def _table_exists(c):
    return bool(c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='lit_experiment_verdicts'").fetchone())


def _norm_prop(c, raw):
    """接受 'a#3' / '3' / 数字 → 返回 lit_propositions.id 或 None"""
    if raw is None:
        return None
    s = str(raw).strip()
    if s.isdigit():
        s = "a#%s" % s
    row = c.execute("SELECT id FROM lit_propositions WHERE prop_key=?", (s,)).fetchone()
    return row[0] if row else None


def _row_to_dict(r):
    (i, pid, verdict, cond, meas, note, att, at, by, status, created) = r
    return {
        "id": i, "proposition_id": pid, "verdict": verdict,
        "conditions": _j(cond), "measured": _j(meas), "evidence_note": note,
        "attachments": _j(att, []), "performed_at": at, "performed_by": by,
        "status": status, "created_at": created,
    }


def _j(s, default=None):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {} if default is None else default


def _body(body):
    if not body:
        return {}
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    except Exception:
        return {}


def _list(c, prop_key=None, limit=100):
    q = """SELECT v.id, p.prop_key, v.verdict, v.conditions_json, v.measured_json,
                  v.evidence_note, v.attachments_json, v.performed_at, v.performed_by,
                  v.status, v.created_at
             FROM lit_experiment_verdicts v
             JOIN lit_propositions p ON p.id = v.proposition_id"""
    args = []
    if prop_key:
        q += " WHERE p.prop_key = ?"
        args.append(prop_key)
    q += " ORDER BY v.created_at DESC LIMIT ?"
    args.append(int(limit))
    return [_row_to_dict(r) for r in c.execute(q, args)]


def _create(c, p):
    key = p.get("proposition_id")
    pid = _norm_prop(c, key)
    if not pid:
        return 400, {"error": "proposition_id not found", "got": key,
                     "hint": "用 'a#3' 或 '3' 这种形式"}
    verdict = str(p.get("verdict") or "").strip()
    if verdict not in VERDICTS:
        return 400, {"error": "verdict invalid", "got": verdict, "allowed": list(VERDICTS)}
    note = str(p.get("evidence_note") or "").strip()
    if not note:
        return 400, {"error": "evidence_note is required（为什么这样裁，不能空）"}
    cond = p.get("conditions")
    if not isinstance(cond, dict) or not cond:
        return 400, {"error": "conditions is required（实验条件不能空：材料体系/工艺/表征）"}
    meas = p.get("measured")
    if not isinstance(meas, dict):
        meas = {"note": str(meas or "")}
    att = p.get("attachments")
    if not isinstance(att, list):
        att = []
    now = time.time()
    cur = c.execute(
        """INSERT INTO lit_experiment_verdicts
           (proposition_id, verdict, conditions_json, measured_json, evidence_note,
            attachments_json, performed_at, performed_by, status, created_at)
           VALUES (?,?,?,?,?,?,?,?, 'proposed', ?)""",
        (pid, verdict, json.dumps(cond, ensure_ascii=False),
         json.dumps(meas, ensure_ascii=False), note[:4000],
         json.dumps(att, ensure_ascii=False), now,
         str(p.get("performed_by") or "")[:80], now))
    c.commit()
    return 201, {"id": cur.lastrowid, "proposition_key": str(key) if str(key).startswith("a#")
                 else "a#%s" % key}


def try_handle(handler, method, parts, qs, body=None):
    if len(parts) < 3 or parts[0] != "v1" or parts[1] != "literature" or parts[2] != "experiments":
        return False
    c = None
    try:
        c = _conn()
        if not _table_exists(c):
            handler._send(503, {"error": "lit_experiment_verdicts 表不存在",
                                "hint": "先执行 literature_propositions_migration.py --apply"})
            return True

        # 列表
        if len(parts) == 3:
            if method == "GET":
                handler._send(200, {"experiments": _list(c, limit=int(qs.get("limit", ["100"])[0] or 100))})
                return True
            if method == "POST":
                code, obj = _create(c, _body(body))
                handler._send(code, obj)
                return True
            handler._send(405, {"error": "method not allowed"})
            return True

        # /experiments/<proposition_key 或 id>
        key = parts[3]
        if len(parts) == 4 and method == "GET":
            # 先按命题找；找不到再按 id 找
            rows = _list(c, prop_key=key)
            if rows:
                handler._send(200, {"proposition_id": key, "experiments": rows})
                return True
            if str(key).isdigit():
                r = c.execute("""SELECT v.id,p.prop_key,v.verdict,v.conditions_json,v.measured_json,
                                        v.evidence_note,v.attachments_json,v.performed_at,
                                        v.performed_by,v.status,v.created_at
                                   FROM lit_experiment_verdicts v
                                   JOIN lit_propositions p ON p.id=v.proposition_id
                                  WHERE v.id=?""", (int(key),)).fetchone()
                if r:
                    handler._send(200, {"experiment": _row_to_dict(r)})
                    return True
            handler._send(404, {"error": "not found", "key": key})
            return True

        # PATCH /experiments/<id>
        if len(parts) == 4 and method == "PATCH":
            if not str(key).isdigit():
                handler._send(400, {"error": "需要数字 id"})
                return True
            p = _body(body)
            st = str(p.get("status") or "").strip()
            if st not in STATUSES:
                handler._send(400, {"error": "status invalid", "allowed": list(STATUSES)})
                return True
            cur = c.execute("UPDATE lit_experiment_verdicts SET status=? WHERE id=?", (st, int(key)))
            c.commit()
            if cur.rowcount == 0:
                handler._send(404, {"error": "experiment not found", "id": key})
            else:
                handler._send(200, {"id": int(key), "status": st})
            return True

        handler._send(405, {"error": "method not allowed"})
        return True
    except Exception as exc:
        try:
            handler._send(500, {"error": str(exc), "kind": type(exc).__name__})
        except Exception:
            pass
        return True
    finally:
        if c is not None:
            c.close()


# ---------------------------------------------------------------- CLI
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="记录/查看实验裁决")
    sub = ap.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add", help="记录一条实验裁决")
    p_add.add_argument("--prop", required=True, help="命题，如 a#3")
    p_add.add_argument("--verdict", required=True, choices=VERDICTS)
    p_add.add_argument("--conditions", default="", help='JSON，如 {"material":"Ti2SnC"}')
    p_add.add_argument("--measured", default="", help='JSON，实测数据')
    p_add.add_argument("--note", required=True, help="为什么这样裁")
    p_add.add_argument("--by", default="")

    p_list = sub.add_parser("list", help="列出裁决")
    p_list.add_argument("--prop", default="")

    p_ok = sub.add_parser("confirm", help="确认一条裁决")
    p_ok.add_argument("--id", type=int, required=True)

    a = ap.parse_args()
    conn = _conn()
    if not _table_exists(conn):
        print("❌ lit_experiment_verdicts 表不存在，先跑迁移")
        raise SystemExit(2)
    if a.cmd == "add":
        code, obj = _create(conn, {
            "proposition_id": a.prop, "verdict": a.verdict,
            "conditions": _j(a.conditions, {}),
            "measured": _j(a.measured, {}),
            "evidence_note": a.note, "performed_by": a.by,
        })
        print(("✅ " if code == 201 else "❌ ") + json.dumps(obj, ensure_ascii=False))
    elif a.cmd == "list":
        rows = _list(conn, prop_key=a.prop or None)
        if not rows:
            print("（暂无实验裁决）")
        for r in rows:
            print("#%-4d %-6s %-14s %-10s %s" % (
                r["id"], r["proposition_id"], r["verdict"], r["status"],
                r["evidence_note"][:50]))
    elif a.cmd == "confirm":
        conn.execute("UPDATE lit_experiment_verdicts SET status='confirmed' WHERE id=?", (a.id,))
        conn.commit()
        print("✅ 已确认 #%d" % a.id)
    else:
        ap.print_help()
    conn.close()
