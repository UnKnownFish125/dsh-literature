#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长任务监控：jobs 存储（阶段 4.1）。

设计要点（来自实际踩过的坑）：
  ① **任务必须落库**，不能只在内存 —— 进程崩了才能知道跑到哪
  ② **必须有 last_heartbeat** —— 这是 nohup + 轮询做不到的：
     heartbeat 超过 stale_after 秒没更新 ⇒ 标 stalled（"卡住"而不是"在跑"）
  ③ 独立文件 jobs.db，**不碰知识库**（零迁移风险）

用法：
    import literature_jobs as J
    jid = J.start("matrix", total=833, meta={"assertions": 49})
    J.tick(jid, done=100)          # 或 J.tick(jid) 自增
    J.finish(jid, error="")        # 完成
    J.list_jobs()
"""
import json
import os
import sqlite3
import threading
import time
import uuid

DB = os.environ.get("LITERATURE_JOBS_DB") or \
    os.path.join(os.environ.get("LITERATURE_DATA_DIR") or "/www/dsh-literature-deploy/literature-server/data", "jobs.db")
STALE_AFTER = 90          # 秒；超过则判 stalled
_LOCK = threading.Lock()


def _conn():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("""CREATE TABLE IF NOT EXISTS jobs(
        id             TEXT PRIMARY KEY,
        kind           TEXT NOT NULL,
        title          TEXT NOT NULL DEFAULT '',
        status         TEXT NOT NULL CHECK(status IN('running','done','failed','stalled','cancelled')),
        done           INTEGER NOT NULL DEFAULT 0,
        total          INTEGER NOT NULL DEFAULT 0,
        started_at     REAL NOT NULL,
        finished_at    REAL,
        last_heartbeat REAL NOT NULL,
        error          TEXT NOT NULL DEFAULT '',
        meta_json      TEXT NOT NULL DEFAULT '{}'
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status, started_at DESC)")
    c.commit()
    return c


def _refresh_stalled(c):
    """把心跳超时的 running 任务标成 stalled（幂等）。"""
    now = time.time()
    c.execute("UPDATE jobs SET status='stalled' "
              "WHERE status='running' AND (? - last_heartbeat) > ?",
              (now, STALE_AFTER))
    c.commit()


def start(kind, total=0, title="", meta=None):
    jid = "%s-%s" % (kind, uuid.uuid4().hex[:10])
    now = time.time()
    with _LOCK:
        c = _conn()
        c.execute("INSERT INTO jobs(id,kind,title,status,done,total,started_at,last_heartbeat,meta_json)"
                  " VALUES(?,?,?,'running',0,?,?,?,?)",
                  (jid, kind, title or kind, int(total), now, now,
                   json.dumps(meta or {}, ensure_ascii=False)))
        c.commit()
    return jid


def tick(jid, done=None, total=None, meta=None):
    """更新进度 + 心跳。done=None 表示自增 1。"""
    with _LOCK:
        c = _conn()
        row = c.execute("SELECT done,total,meta_json FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            return None
        cur_done, cur_total, cur_meta = row
        new_done = (cur_done + 1) if done is None else int(done)
        new_total = cur_total if total is None else int(total)
        new_meta = cur_meta if meta is None else json.dumps(meta, ensure_ascii=False)
        c.execute("UPDATE jobs SET done=?, total=?, last_heartbeat=?, meta_json=? WHERE id=?",
                  (new_done, new_total, time.time(), new_meta, jid))
        c.commit()
    return new_done


def finish(jid, error="", status=None):
    st = status or ("failed" if error else "done")
    with _LOCK:
        c = _conn()
        c.execute("UPDATE jobs SET status=?, finished_at=?, last_heartbeat=?, error=? WHERE id=?",
                  (st, time.time(), time.time(), (error or "")[:900], jid))
        c.commit()


def cancel(jid, error="cancelled by user"):
    finish(jid, error=error, status="cancelled")


def list_jobs(limit=50, active_only=False):
    c = _conn()
    _refresh_stalled(c)
    q = "SELECT id,kind,title,status,done,total,started_at,finished_at,last_heartbeat,error,meta_json" \
        " FROM jobs"
    if active_only:
        q += " WHERE status IN('running','stalled')"
    q += " ORDER BY started_at DESC LIMIT ?"
    out = []
    now = time.time()
    for r in c.execute(q, (int(limit),)):
        (jid, kind, title, status, done, total, st_at, fin_at, hb, err, meta) = r
        elapsed = (fin_at or now) - st_at
        pct = (100.0 * done / total) if total else None
        eta = None
        if status == "running" and pct and done > 0:
            eta = max(0.0, elapsed * (total - done) / done)
        out.append({
            "id": jid, "kind": kind, "title": title, "status": status,
            "done": done, "total": total, "percent": round(pct, 1) if pct is not None else None,
            "started_at": st_at, "finished_at": fin_at,
            "elapsed_sec": round(elapsed, 1),
            "eta_sec": round(eta, 1) if eta is not None else None,
            "heartbeat_age_sec": round(now - hb, 1),
            "error": err,
            "meta": _safe_json(meta),
        })
    return out


def _safe_json(s):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}


def counts():
    c = _conn()
    _refresh_stalled(c)
    out = {}
    for st, n in c.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status"):
        out[st] = n
    return out


# ---------------------------------------------------------------- CLI
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        js = list_jobs(limit=20)
        if not js:
            print("（无任务）")
        for j in js:
            icon = {"running": "▶", "done": "✓", "failed": "✗",
                    "stalled": "⚠", "cancelled": "⊘"}.get(j["status"], "?")
            pct = ("%5.1f%%" % j["percent"]) if j["percent"] is not None else "  --  "
            eta = (" 剩余 %.0fs" % j["eta_sec"]) if j["eta_sec"] else ""
            print("%s %-10s %-30s %s %d/%d%s  (%s)" % (
                icon, j["kind"], j["title"][:30], pct, j["done"], j["total"],
                eta, j["id"][-12:]))
            if j["error"]:
                print("    错误:", j["error"][:120])
        print()
        print("状态计数:", counts())
    elif cmd == "demo":
        jid = start("demo", total=10, title="演示任务")
        for i in range(10):
            time.sleep(0.3)
            tick(jid)
        finish(jid)
        print("完成:", jid)
    else:
        print("用法: python3 literature_jobs.py [list|demo]")
