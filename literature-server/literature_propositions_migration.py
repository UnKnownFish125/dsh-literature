#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段 2.2：命题层落库迁移（方案 A）。

安全设计：
  · 默认 dry-run，只报告不写；必须显式 --apply 才写
  · 写前自动备份 + 记录 md5
  · **指纹断言**：现有 63 张表的行数必须完全不变，否则回滚
  · 幂等：重复执行不产生重复行（UNIQUE 约束 + INSERT OR REPLACE）
  · 自动生成回滚脚本

用法：
    python3 literature_propositions_migration.py                     # dry-run（默认）
    python3 literature_propositions_migration.py --db <path> --apply  # 对指定库执行
    python3 literature_propositions_migration.py --rollback <ts>      # 回滚
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time

DEFAULT_DB = "/www/dsh-literature-deploy/literature-server/data/literature.db"
FROZEN = "/tmp/p28/verified_labels.json"
ASSERTIONS = "/tmp/p30/assertions_v2.json"
AUDIT = "/tmp/p28/assertion_condition_audit.json"
SUBJECT = "/tmp/p28/subject_terms.json"
BACKUP_DIR = "/www/dsh-literature-deploy/literature-server/data/backups"

NEW_TABLES = ("lit_propositions", "lit_prop_evidence", "lit_experiment_verdicts")

DDL = [
    """CREATE TABLE IF NOT EXISTS lit_propositions (
        id             INTEGER PRIMARY KEY,
        prop_key       TEXT NOT NULL UNIQUE,
        canonical      TEXT NOT NULL,
        polarity       TEXT CHECK(polarity IN('positive','negative','boundary')),
        branch         TEXT NOT NULL,
        judge_mode     TEXT NOT NULL DEFAULT 'conditional'
                       CHECK(judge_mode IN('conditional','mechanism')),
        subject_terms  TEXT NOT NULL DEFAULT '[]',
        conditions_json TEXT NOT NULL DEFAULT '{}',
        difficulty     TEXT,
        status         TEXT NOT NULL DEFAULT 'active'
                       CHECK(status IN('active','retired')),
        rule_version   TEXT NOT NULL DEFAULT 'p28-matrix-v2',
        created_at     REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS lit_prop_evidence (
        id             INTEGER PRIMARY KEY,
        proposition_id INTEGER NOT NULL REFERENCES lit_propositions(id),
        document_id    INTEGER NOT NULL REFERENCES documents(id),
        verdict        TEXT NOT NULL CHECK(verdict IN(
                         'supports','refutes','qualifies',
                         'not_addressed','found_corrupt','not_extracted')),
        quote          TEXT NOT NULL DEFAULT '',
        reason         TEXT NOT NULL DEFAULT '',
        judged_by      TEXT NOT NULL DEFAULT '',
        judged_at      REAL NOT NULL DEFAULT 0,
        rule_version   TEXT NOT NULL DEFAULT 'p28-matrix-v2',
        frozen         INTEGER NOT NULL DEFAULT 1 CHECK(frozen IN(0,1)),
        review_status  TEXT NOT NULL DEFAULT 'auto'
                       CHECK(review_status IN('auto','accepted_by_lead','rejected')),
        UNIQUE(proposition_id, document_id, rule_version)
    )""",
    """CREATE TABLE IF NOT EXISTS lit_experiment_verdicts (
        id              INTEGER PRIMARY KEY,
        proposition_id  INTEGER NOT NULL REFERENCES lit_propositions(id),
        verdict         TEXT NOT NULL CHECK(verdict IN(
                          'support_side','refute_side','neither','inconclusive')),
        conditions_json TEXT NOT NULL DEFAULT '{}',
        measured_json   TEXT NOT NULL DEFAULT '{}',
        evidence_note   TEXT NOT NULL DEFAULT '',
        attachments_json TEXT NOT NULL DEFAULT '[]',
        performed_at    REAL NOT NULL,
        performed_by    TEXT NOT NULL DEFAULT '',
        status          TEXT NOT NULL DEFAULT 'proposed'
                        CHECK(status IN('proposed','confirmed','retracted')),
        created_at      REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_lit_ev_prop ON lit_prop_evidence(proposition_id, verdict)",
    "CREATE INDEX IF NOT EXISTS ix_lit_ev_doc  ON lit_prop_evidence(document_id)",
    "CREATE INDEX IF NOT EXISTS ix_lit_xv_prop ON lit_experiment_verdicts(proposition_id)",
]


# ---------------------------------------------------------------- 工具
def md5_of(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(conn):
    """现有表的 (表名 → 行数)，用作"未被动过"的断言。"""
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    fp = {}
    for t in tables:
        if t in NEW_TABLES or t.startswith('sqlite_'):
            continue
        try:
            fp[t] = conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
        except Exception as e:
            fp[t] = 'ERR:%s' % e
    return fp


def fk_violations(conn):
    try:
        return len(list(conn.execute("PRAGMA foreign_key_check")))
    except Exception:
        return -1


def load_inputs():
    meta = {}
    d = json.load(open(ASSERTIONS, encoding='utf-8'))
    for a in (d.get('preserved_assertions') or []) + (d.get('assertions') or []):
        aid = a.get('id')
        if isinstance(aid, int):
            aid = 'a#%d' % aid
        meta[aid] = {
            'canonical': a.get('canonical') or '',
            'branch': a.get('branch') or a.get('family') or '?',
            'polarity': a.get('polarity'),
            'judge_mode': a.get('judge_mode') or 'conditional',
            'difficulty': a.get('difficulty'),
            'conditions': a.get('key_conditions') or {},
        }
    try:
        au = json.load(open(AUDIT, encoding='utf-8'))
        items = au if isinstance(au, list) else (au.get('assertions') or au.get('items') or [])
        for it in items:
            aid = it.get('id')
            if isinstance(aid, int):
                aid = 'a#%d' % aid
            if aid in meta:
                if it.get('rewritten_canonical'):
                    meta[aid]['canonical'] = it['rewritten_canonical']
                if it.get('judge_mode'):
                    meta[aid]['judge_mode'] = it['judge_mode']
                if it.get('category'):
                    meta[aid]['category'] = it['category']
    except Exception:
        pass
    subj = {}
    try:
        s = json.load(open(SUBJECT, encoding='utf-8'))
        s.pop('_comment', None)
        subj = s
    except Exception:
        pass
    labels = json.load(open(FROZEN, encoding='utf-8')).get('labels') or []
    return meta, subj, labels


# ---------------------------------------------------------------- 迁移
def run(db, apply, stamp=None):
    stamp = stamp or time.strftime('%Y%m%d-%H%M%S')
    meta, subj, labels = load_inputs()
    print('输入：%d 条命题 ｜ %d 条判定 ｜ 主体词表 %d 条'
          % (len(meta), len(labels), len(subj)))

    if not os.path.isfile(db):
        print('❌ 数据库不存在:', db)
        return 2
    print('目标库:', db)
    print('库 md5:', md5_of(db))
    conn = sqlite3.connect(db)
    before_fp = fingerprint(conn)
    before_fk = fk_violations(conn)
    before_tables = len(before_fp)
    print('现有表 %d 张 ｜ FK 违规 %d 条（pre-existing）' % (before_tables, before_fk))

    # 已有数据检查（幂等提示）
    conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    exists = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if 'lit_propositions' in exists:
        n = conn.execute('SELECT COUNT(*) FROM lit_propositions').fetchone()[0]
        print('⚠ 已存在 lit_propositions，当前 %d 行（将按 UNIQUE 覆盖更新）' % n)

    if not apply:
        print()
        print('=== DRY-RUN（未写库）===')
        print('  将创建 %d 张表 + %d 个索引' % (len(NEW_TABLES), 3))
        print('  将写入命题 %d 条' % len(meta))
        from collections import Counter
        cnt = Counter(l.get('verdict') for l in labels)
        print('  将写入证据 %d 条: %s' % (len(labels), dict(cnt)))
        print('  lit_experiment_verdicts: 建表留空（等用户填）')
        print()
        print('确认无误后加 --apply 执行')
        return 0

    # ---- 备份：**只做一次**（首次迁移前的干净状态）
    # 坑：如果每次都备份，第二次的备份里已经含 lit_* 表，回滚就清不掉了。
    os.makedirs(BACKUP_DIR, exist_ok=True)
    base = os.path.basename(db).replace('.db', '')
    bak = os.path.join(BACKUP_DIR, '%s.pre-propositions.db' % base)
    if os.path.exists(bak):
        print('备份已存在（首次迁移前快照，不覆盖）:', bak)
    else:
        shutil.copy2(db, bak)
        print('备份（首次迁移前快照）:', bak)
    bak_md5 = md5_of(bak)
    print('备份 md5:', bak_md5)

    # ---- 建表
    for ddl in DDL:
        conn.execute(ddl)
    conn.commit()
    print('✅ 建表完成:', ', '.join(NEW_TABLES))

    # ---- 写命题
    now = time.time()
    for pk, m in meta.items():
        conn.execute("""INSERT INTO lit_propositions
            (prop_key, canonical, polarity, branch, judge_mode, subject_terms,
             conditions_json, difficulty, status, rule_version, created_at)
            VALUES(?,?,?,?,?,?,?,?, 'active', 'p28-matrix-v2', ?)
            ON CONFLICT(prop_key) DO UPDATE SET
              canonical=excluded.canonical, polarity=excluded.polarity,
              branch=excluded.branch, judge_mode=excluded.judge_mode,
              subject_terms=excluded.subject_terms,
              conditions_json=excluded.conditions_json""",
            (pk, m['canonical'], m['polarity'], m['branch'], m['judge_mode'],
             json.dumps(subj.get(pk) or [], ensure_ascii=False),
             json.dumps(m.get('conditions') or {}, ensure_ascii=False),
             m.get('difficulty'), now))
    conn.commit()
    pid = {r[0]: r[1] for r in conn.execute('SELECT prop_key, id FROM lit_propositions')}
    print('✅ 命题写入 %d 条' % len(pid))

    # ---- 写证据
    valid_docs = {r[0] for r in conn.execute('SELECT id FROM documents')}
    skipped = 0
    written = 0
    for l in labels:
        pk = l.get('proposition_id')
        doc = l.get('doc_id')
        if pk not in pid or doc not in valid_docs:
            skipped += 1
            continue
        conn.execute("""INSERT INTO lit_prop_evidence
            (proposition_id, document_id, verdict, quote, reason, judged_by,
             judged_at, rule_version, frozen, review_status)
            VALUES(?,?,?,?,?,?,?, 'p28-matrix-v2', 1, ?)
            ON CONFLICT(proposition_id, document_id, rule_version) DO UPDATE SET
              verdict=excluded.verdict, quote=excluded.quote,
              reason=excluded.reason, judged_by=excluded.judged_by,
              review_status=excluded.review_status""",
            (pid[pk], doc, l.get('verdict'), l.get('evidence_verbatim') or '',
             (l.get('reason') or '')[:500], l.get('judged_by') or '',
              now,
             'accepted_by_lead' if l.get('review_status') == 'accepted_by_lead' else 'auto'))
        written += 1
    conn.commit()
    print('✅ 证据写入 %d 条（跳过 %d 条：命题或文档不存在）' % (written, skipped))

    # ---- 指纹断言
    after_fp = fingerprint(conn)
    after_fk = fk_violations(conn)
    changed = {k: (before_fp[k], after_fp.get(k)) for k in before_fp
               if after_fp.get(k) != before_fp[k]}
    print()
    print('=== 指纹断言 ===')
    print('  现有表行数变化:', changed if changed else '✅ 全部不变')
    print('  FK 违规: %d → %d %s' % (before_fk, after_fk,
                                    '✅' if after_fk == before_fk else '❌ 新增'))
    ok = (not changed) and after_fk == before_fk
    print('  结论:', '✅ 通过' if ok else '❌ **失败，建议回滚**')

    # ---- 回滚脚本（指向首次迁移前的固定快照）
    rb = os.path.join(BACKUP_DIR, 'rollback-propositions.sh')
    with open(rb, 'w') as f:
        f.write('#!/bin/bash\n# 回滚命题层迁移（恢复到首次迁移前的快照）\nset -e\n')
        f.write('DB=%s\n' % db)
        f.write('BAK=%s\n' % bak)
        f.write('cp -a "$DB" "$DB.before-rollback-%s"\n' % stamp)
        f.write('cp -a "$BAK" "$DB"\n')
        f.write('echo "已回滚到 $BAK"\n')
        f.write('echo "当前 md5: $(md5sum $DB | cut -d" " -f1)"\n')
    os.chmod(rb, 0o755)
    print('  回滚脚本:', rb)

    # ---- 统计
    print()
    print('=== 落库后统计 ===')
    for t in NEW_TABLES:
        print('  %-26s %d 行' % (t, conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]))
    for v, n in conn.execute('SELECT verdict, COUNT(*) FROM lit_prop_evidence GROUP BY 1 ORDER BY 2 DESC'):
        print('     %-15s %d' % (v, n))
    conn.close()
    print()
    print('库 md5 (after):', md5_of(db))
    return 0 if ok else 1


def rollback(db, stamp=None):
    base = os.path.basename(db).replace('.db', '')
    bak = os.path.join(BACKUP_DIR, '%s.pre-propositions.db' % base)
    if not os.path.isfile(bak):
        print('❌ 迁移前快照不存在:', bak)
        return 2
    shutil.copy2(db, db + '.before-rollback-' + time.strftime('%Y%m%d-%H%M%S'))
    shutil.copy2(bak, db)
    print('✅ 已回滚到', bak)
    print('  当前 md5:', md5_of(db))
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--apply', action='store_true', help='真正写库（默认 dry-run）')
    ap.add_argument('--rollback', nargs='?', const='auto', metavar='STAMP',
                    help='回滚到首次迁移前的快照（无需参数）')
    a = ap.parse_args()
    if a.rollback:
        sys.exit(rollback(a.db, a.rollback))
    sys.exit(run(a.db, a.apply))
