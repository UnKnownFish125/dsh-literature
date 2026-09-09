#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_skill_schema.py — skill 管理体系的显式迁移框架与表结构。

设计依据：docs/dsh-literature-skill-management-v02.md（v0.2 + 数据契约章节）
评审依据：docs/skill-management-review-astra-final-20260909.md

关键约束（均有实测/评审支撑）：
- 不使用 `install_schema` 的 CREATE TABLE IF NOT EXISTS 承载变更（实测无迁移能力），
  本模块自建 `schema_migrations` 版本表，按版本增量、显式事务应用。
- `scope=global` → `workspace_id IS NULL`；`scope=workspace` → 真实非空 UUID。
  禁止用空串表示全局（139 条事故模式）。
- slug 唯一性用 partial unique index 分别约束 global / workspace，不用含 NULL 的复合 UNIQUE。
- 内容版本不可原地修改；`skill_versions` 只追加。
- 部署状态与版本分离（desired / applied），失败不得写"已发布"。
"""

import os
import sqlite3
import time

SCHEMA_VERSION = 1

# ── 迁移 1：skill 管理体系初始表结构 ────────────────────────────────────────
_MIGRATION_1 = [
    # 1. skills：管理态元数据
    """
    CREATE TABLE IF NOT EXISTS skills (
      id                TEXT PRIMARY KEY,
      slug              TEXT NOT NULL,
      title             TEXT NOT NULL DEFAULT '',
      description       TEXT NOT NULL DEFAULT '',
      category_id       INTEGER,
      scope             TEXT NOT NULL DEFAULT 'workspace' CHECK(scope IN ('global','workspace')),
      workspace_id      TEXT,
      origin_workspace_id TEXT,
      lifecycle         TEXT NOT NULL DEFAULT 'draft'
                        CHECK(lifecycle IN ('draft','active','deprecated','archived')),
      visibility        TEXT NOT NULL DEFAULT 'user-only'
                        CHECK(visibility IN ('model','user-only')),
      active_version_id INTEGER,
      row_version       INTEGER NOT NULL DEFAULT 1,
      created_by        TEXT NOT NULL DEFAULT '',
      created_at        REAL NOT NULL,
      updated_at        REAL NOT NULL,
      deleted_at        REAL,
      CHECK (
        (scope = 'global'    AND workspace_id IS NULL) OR
        (scope = 'workspace' AND workspace_id IS NOT NULL AND length(trim(workspace_id)) > 0)
      )
    )
    """,
    # slug 唯一：分别约束全局与工作区（partial unique，避免 NULL 语义问题）
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_skills_slug_global ON skills(slug) WHERE scope='global' AND deleted_at IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_skills_slug_ws ON skills(workspace_id, slug) WHERE scope='workspace' AND deleted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_skills_lifecycle ON skills(lifecycle, updated_at)",
    "CREATE INDEX IF NOT EXISTS ix_skills_category ON skills(category_id)",

    # 2. skill_versions：不可变版本快照
    """
    CREATE TABLE IF NOT EXISTS skill_versions (
      id                  INTEGER PRIMARY KEY AUTOINCREMENT,
      skill_id            TEXT NOT NULL REFERENCES skills(id),
      version             INTEGER NOT NULL,
      parent_version_id   INTEGER REFERENCES skill_versions(id),
      skill_md            TEXT NOT NULL DEFAULT '',
      frontmatter_json    TEXT NOT NULL DEFAULT '{}',
      content_sha256      TEXT NOT NULL DEFAULT '',
      artifact_sha256     TEXT NOT NULL DEFAULT '',
      artifact_uri        TEXT NOT NULL DEFAULT '',
      manifest_json       TEXT NOT NULL DEFAULT '{}',
      source_kind         TEXT NOT NULL DEFAULT 'manual'
                          CHECK(source_kind IN ('github','distilled','manual','imported')),
      source_url          TEXT NOT NULL DEFAULT '',
      source_ref          TEXT NOT NULL DEFAULT '',
      source_key          TEXT NOT NULL DEFAULT '',
      distilled_from_json TEXT NOT NULL DEFAULT '[]',
      dependencies_json   TEXT NOT NULL DEFAULT '[]',
      compatibility_json  TEXT NOT NULL DEFAULT '{}',
      permission_requests_json TEXT NOT NULL DEFAULT '[]',
      review_status       TEXT NOT NULL DEFAULT 'pending'
                          CHECK(review_status IN ('pending','approved','rejected')),
      reviewed_by         TEXT NOT NULL DEFAULT '',
      reviewed_at         REAL,
      created_by          TEXT NOT NULL DEFAULT '',
      created_at          REAL NOT NULL,
      UNIQUE(skill_id, version)
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_skill_versions_source_key ON skill_versions(source_key) WHERE source_key <> ''",
    "CREATE INDEX IF NOT EXISTS ix_skill_versions_skill ON skill_versions(skill_id, version DESC)",

    # 3. skill_files：整包资源（bundle 支持）
    """
    CREATE TABLE IF NOT EXISTS skill_files (
      id               INTEGER PRIMARY KEY AUTOINCREMENT,
      skill_version_id INTEGER NOT NULL REFERENCES skill_versions(id),
      rel_path         TEXT NOT NULL,
      size_bytes       INTEGER NOT NULL DEFAULT 0,
      sha256           TEXT NOT NULL DEFAULT '',
      mode             INTEGER NOT NULL DEFAULT 420,
      is_symlink       INTEGER NOT NULL DEFAULT 0,
      UNIQUE(skill_version_id, rel_path),
      CHECK(rel_path NOT LIKE '/%' AND rel_path NOT LIKE '%..%')
    )
    """,

    # 4. skill_deployments：部署状态机（desired/applied 分离）
    """
    CREATE TABLE IF NOT EXISTS skill_deployments (
      id                    INTEGER PRIMARY KEY AUTOINCREMENT,
      skill_id              TEXT NOT NULL REFERENCES skills(id),
      skill_version_id      INTEGER NOT NULL REFERENCES skill_versions(id),
      target_id             TEXT NOT NULL,
      target_scope          TEXT NOT NULL DEFAULT 'global',
      workspace_id          TEXT,
      root_dir              TEXT NOT NULL,
      deployed_path         TEXT NOT NULL DEFAULT '',
      desired_version_id    INTEGER REFERENCES skill_versions(id),
      applied_version_id    INTEGER REFERENCES skill_versions(id),
      expected_current_hash TEXT NOT NULL DEFAULT '',
      observed_hash         TEXT NOT NULL DEFAULT '',
      generation            INTEGER NOT NULL DEFAULT 0,
      state                 TEXT NOT NULL DEFAULT 'pending'
                            CHECK(state IN ('pending','applying','verified','failed','drift','removed')),
      attempt_count         INTEGER NOT NULL DEFAULT 0,
      next_retry_at         REAL,
      last_error            TEXT NOT NULL DEFAULT '',
      last_verified_at      REAL,
      operation_key         TEXT NOT NULL DEFAULT '',
      created_at            REAL NOT NULL,
      updated_at            REAL NOT NULL,
      UNIQUE(skill_id, target_id)
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_skill_deployments_opkey ON skill_deployments(operation_key) WHERE operation_key <> ''",
    "CREATE INDEX IF NOT EXISTS ix_skill_deployments_state ON skill_deployments(state, updated_at)",

    # 5. skill_usage_events：加载/应用事件（幂等）
    """
    CREATE TABLE IF NOT EXISTS skill_usage_events (
      id                    INTEGER PRIMARY KEY AUTOINCREMENT,
      producer_id           TEXT NOT NULL DEFAULT '',
      event_key             TEXT NOT NULL,
      event_kind            TEXT NOT NULL DEFAULT 'load' CHECK(event_kind IN ('load','apply')),
      invocation_kind       TEXT NOT NULL DEFAULT 'tool' CHECK(invocation_kind IN ('tool','slash','unknown')),
      skill_id              TEXT,
      skill_version_id      INTEGER REFERENCES skill_versions(id),
      deployment_id         INTEGER REFERENCES skill_deployments(id),
      skill_name            TEXT NOT NULL DEFAULT '',
      observed_content_hash TEXT NOT NULL DEFAULT '',
      session_id            TEXT NOT NULL DEFAULT '',
      turn_id               TEXT NOT NULL DEFAULT '',
      tool_call_id          TEXT NOT NULL DEFAULT '',
      run_id                TEXT NOT NULL DEFAULT '',
      workspace_id          TEXT NOT NULL DEFAULT '',
      occurred_at           REAL NOT NULL,
      created_at            REAL NOT NULL,
      UNIQUE(producer_id, event_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_skill_events_skill ON skill_usage_events(skill_id, occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_skill_events_version ON skill_usage_events(skill_version_id, occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_skill_events_ws ON skill_usage_events(workspace_id, occurred_at DESC)",

    # 6. skill_evaluations：评价（三源分列）
    """
    CREATE TABLE IF NOT EXISTS skill_evaluations (
      id               INTEGER PRIMARY KEY AUTOINCREMENT,
      skill_id         TEXT,
      skill_version_id INTEGER REFERENCES skill_versions(id),
      usage_event_id   INTEGER REFERENCES skill_usage_events(id),
      run_id           TEXT NOT NULL DEFAULT '',
      kind             TEXT NOT NULL
                       CHECK(kind IN ('user_rating','agent_self','task_outcome','approval')),
      reviewer_id      TEXT NOT NULL DEFAULT '',
      model_id         TEXT NOT NULL DEFAULT '',
      rubric_version   TEXT NOT NULL DEFAULT '',
      score            REAL,
      outcome          TEXT CHECK(outcome IS NULL OR outcome IN ('success','failure','unknown','cancelled')),
      decision         TEXT CHECK(decision IS NULL OR decision IN ('approve','reject')),
      evidence_ref     TEXT NOT NULL DEFAULT '',
      comment          TEXT NOT NULL DEFAULT '',
      created_at       REAL NOT NULL,
      CHECK (
        (kind = 'user_rating' AND (score IS NULL OR (score >= 1 AND score <= 5))) OR
        (kind = 'agent_self'  AND (score IS NULL OR (score >= 0 AND score <= 1))) OR
        (kind IN ('task_outcome','approval'))
      )
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_skill_evals_version ON skill_evaluations(skill_version_id, kind, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_skill_evals_run ON skill_evaluations(run_id)",

    # 7. skill_audit：审计（谁把什么写进了指令面）
    """
    CREATE TABLE IF NOT EXISTS skill_audit (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      principal_id TEXT NOT NULL DEFAULT '',
      action       TEXT NOT NULL,
      target_type  TEXT NOT NULL DEFAULT '',
      target_id    TEXT NOT NULL DEFAULT '',
      request_id   TEXT NOT NULL DEFAULT '',
      details_json TEXT NOT NULL DEFAULT '{}',
      created_at   REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_skill_audit_target ON skill_audit(target_type, target_id, created_at DESC)",
]

MIGRATIONS = {1: _MIGRATION_1}


def _applied_versions(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version    INTEGER PRIMARY KEY,
          applied_at REAL NOT NULL,
          checksum   TEXT NOT NULL DEFAULT '',
          note       TEXT NOT NULL DEFAULT ''
        )
    """)
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def install_skill_schema(conn, note=""):
    """按版本增量应用 skill 相关迁移（显式事务，幂等）。

    返回 (from_version, to_version, applied_list)。
    """
    done = _applied_versions(conn)
    current = max(done) if done else 0
    applied = []
    for version in sorted(MIGRATIONS):
        if version in done:
            continue
        stmts = MIGRATIONS[version]
        try:
            conn.execute("BEGIN")
            for stmt in stmts:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at, checksum, note) VALUES (?,?,?,?)",
                (version, time.time(), _checksum(stmts), note),
            )
            conn.commit()
            applied.append(version)
        except Exception:
            conn.rollback()
            raise
    return current, (max(applied) if applied else current), applied


def _checksum(stmts):
    import hashlib
    h = hashlib.sha256()
    for s in stmts:
        h.update(s.encode("utf-8"))
    return h.hexdigest()[:16]


def ensure_skill_schema(db_path, note=""):
    """便捷入口：对指定 sqlite 文件应用 skill 迁移。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        return install_skill_schema(conn, note=note)
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "literature.db")
    frm, to, applied = ensure_skill_schema(target, note="cli")
    print(f"schema_migrations: {frm} → {to} | applied={applied} | db={target}")
