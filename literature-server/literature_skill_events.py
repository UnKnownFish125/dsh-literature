#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_skill_events.py — skill 加载/应用事件与评价的接收、幂等落库与统计。

设计依据：
- docs/dsh-literature-skill-management-v02.md §7「数据来源与采集契约」（7.4 接口契约、硬约定）
- docs/skill-management-review-astra-final-20260909.md（统计口径 / 版本关联 / 幂等）
表结构来源：literature_skill_schema.py（skill_usage_events / skill_evaluations / skill_deployments）

职责边界（方案 7.3）：literature 只做「存储 + 分析」，不直接读会话日志；
事件由日志注入插件通过 POST /v1/skill-events 上报，本模块只负责落库与口径。

硬约定（均有实测/评审支撑，违反即产生错误统计）：
1. 幂等由数据库唯一约束 `UNIQUE(producer_id, event_key)` 保证；应用层只做回读，
   不用「先查再插」冒充幂等（并发下会翻倍）。
2. `skill_version_id` 不确定就 NULL：只在 `skill_deployments` 的「已核验时间窗」内关联；
   禁止按 slug 关联最新版；窗口内多版本歧义 → NULL（记 unknown，不冒充精确版本）。
3. `workspace_id` 必须由调用方按 #668 规则（DSH_SESSION_ID → workspace.json）解析后传入；
   本模块不做任何兜底/推断，缺失即拒收——绝不写假工作区（139 条事故模式）。
4. tool 与 `/slug` 两条调用路径都必须上报，用 `invocation_kind` 分列；未声明一律记
   `unknown`，不默认成 `tool`（防止把 `/slug` 计成工具调用）。
5. 三源评价分列：`user_rating`(1-5) / `agent_self`(0-1) / `task_outcome` / `approval`；
   统计时**不跨用户分与 agent 分混合平均**。
6. effectiveness 只用「已评价的 distinct run」算 `success/(success+failure)`；
   无评价返回 None；`unknown`/`cancelled` 不算失败。
"""

import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

try:  # 同目录导入（部署目录）
    from literature_skill_schema import install_skill_schema
except ImportError:  # 允许从其他 cwd 调用
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from literature_skill_schema import install_skill_schema

__all__ = [
    "SkillEventError",
    "ValidationError",
    "SkillEventStore",
    "EVENT_KINDS",
    "INVOCATION_KINDS",
    "EVALUATION_KINDS",
    "OUTCOMES",
    "DECISIONS",
]

EVENT_KINDS = ("load", "apply")
INVOCATION_KINDS = ("tool", "slash", "unknown")
EVALUATION_KINDS = ("user_rating", "agent_self", "task_outcome", "approval")
OUTCOMES = ("success", "failure", "unknown", "cancelled")
DECISIONS = ("approve", "reject")

# 用户星级与 agent 自评的量纲不同，分开校验、分开聚合
SCORE_RANGES = {"user_rating": (1.0, 5.0), "agent_self": (0.0, 1.0)}

# epoch 秒 / 毫秒判定阈值（契约 7.4 的 occurred_at 是毫秒）
_MS_THRESHOLD = 1e11

# 事件「逻辑去重键」：同一逻辑事件即使被多个 producer 上报也只算一次。
# 优先 tool_call_id（工具路径唯一），其次 session+turn（/slug 路径），
# 最后退回 DB 幂等键（producer_id + event_key）。
_DEDUP_KEY_SQL = """
CASE
  WHEN tool_call_id <> '' THEN 'tool:' || session_id || ':' || tool_call_id
  WHEN session_id <> '' AND turn_id <> ''
    THEN 'turn:' || session_id || ':' || turn_id || ':' || event_kind || ':' || invocation_kind
  ELSE 'key:' || producer_id || ':' || event_key
END
"""


class SkillEventError(Exception):
    """本模块的基类异常。"""


class ValidationError(SkillEventError):
    """上报载荷不合法（缺字段/越界/语义冲突）。"""


def _now():
    return time.time()


def _iso(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _normalize_ts(value, field="occurred_at", required=False, default=None):
    """统一时间戳到 epoch 秒；接受秒或毫秒（契约 7.4 用毫秒）。"""
    if value is None or value == "":
        if required:
            raise ValidationError(f"{field} is required (epoch seconds or milliseconds)")
        return default
    try:
        ts = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a numeric epoch timestamp, got {value!r}")
    if ts <= 0:
        raise ValidationError(f"{field} must be positive, got {ts!r}")
    if ts >= _MS_THRESHOLD:  # 毫秒 → 秒
        ts = ts / 1000.0
    return ts


def _run_key(session_id, turn_id):
    """无显式 run_id 时的稳定派生键；两者不全则不猜（返回空）。"""
    session_id = (session_id or "").strip()
    turn_id = (turn_id or "").strip()
    if session_id and turn_id:
        return f"{session_id}:{turn_id}"
    return ""


class SkillEventStore:
    """skill 事件/评价存储与分析层。

    - 写入事件必须显式携带 workspace_id（#668 解析结果），本层不兜底。
    - 版本关联只在已核验部署的时间窗内发生，不确定即 NULL。
    """

    def __init__(self, db_path, ensure_schema=True, grace_seconds=0.0):
        self.db_path = db_path
        # 允许的时钟偏移（秒）：事件时间可能略早于部署核验时间
        self.grace_seconds = float(grace_seconds or 0.0)
        if ensure_schema:
            self._ensure_schema()

    # ------------------------------------------------------------ plumbing

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self):
        conn = self._connect()
        try:
            install_skill_schema(conn, note="literature_skill_events")
        finally:
            conn.close()

    @staticmethod
    def _event_to_dict(row):
        d = dict(row)
        d["occurred_at_iso"] = _iso(d.get("occurred_at"))
        d["created_at_iso"] = _iso(d.get("created_at"))
        return d

    @staticmethod
    def _evaluation_to_dict(row):
        d = dict(row)
        d["created_at_iso"] = _iso(d.get("created_at"))
        return d

    # -------------------------------------------------------- resolution

    def resolve_skill(self, skill_name, workspace_id):
        """按 slug 解析 skill_id：workspace 私有优先，其次 global；找不到返回 None。

        只做「身份解析」，不参与版本选择。
        """
        skill_name = (skill_name or "").strip()
        workspace_id = (workspace_id or "").strip()
        if not skill_name:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM skills
                 WHERE slug=? AND deleted_at IS NULL
                   AND ((scope='workspace' AND workspace_id=?) OR scope='global')
                 ORDER BY CASE WHEN scope='workspace' THEN 0 ELSE 1 END
                 LIMIT 1
                """,
                (skill_name, workspace_id),
            ).fetchone()
        return row["id"] if row else None

    def _resolve_skill_id(self, conn, explicit_skill_id, skill_name, workspace_id):
        if explicit_skill_id:
            row = conn.execute(
                "SELECT id, scope, workspace_id FROM skills WHERE id=? AND deleted_at IS NULL",
                (str(explicit_skill_id),),
            ).fetchone()
            if row is None:
                raise ValidationError(f"skill_id {explicit_skill_id!r} not found (or soft-deleted)")
            if row["scope"] == "workspace" and (row["workspace_id"] or "") != workspace_id:
                raise ValidationError(
                    f"skill_id {explicit_skill_id!r} belongs to workspace "
                    f"{row['workspace_id']!r}, not {workspace_id!r}"
                )
            return row["id"]
        if not skill_name:
            return None
        row = conn.execute(
            """
            SELECT id FROM skills
             WHERE slug=? AND deleted_at IS NULL
               AND ((scope='workspace' AND workspace_id=?) OR scope='global')
             ORDER BY CASE WHEN scope='workspace' THEN 0 ELSE 1 END
             LIMIT 1
            """,
            (skill_name, workspace_id),
        ).fetchone()
        return row["id"] if row else None

    def _resolve_version_by_window(self, conn, skill_id, workspace_id, occurred_at):
        """用部署时间窗关联版本。返回 dict：

        {skill_version_id, deployment_id, reason, matched_at, candidates}

        reason ∈ deployment_window | no_skill_id | no_verified_deployment |
                 before_first_verified_deployment | no_version_in_deployment |
                 ambiguous_within_window
        """
        out = {
            "skill_version_id": None,
            "deployment_id": None,
            "reason": "unresolved",
            "matched_at": None,
            "candidates": [],
        }
        if not skill_id:
            out["reason"] = "no_skill_id"
            return out
        rows = conn.execute(
            """
            SELECT id, applied_version_id, skill_version_id, workspace_id,
                   COALESCE(last_verified_at, updated_at, created_at) AS verified_at
              FROM skill_deployments
             WHERE skill_id=? AND state='verified' AND last_verified_at IS NOT NULL
               AND (workspace_id IS NULL OR workspace_id='' OR workspace_id=?)
             ORDER BY verified_at DESC, id DESC
            """,
            (skill_id, workspace_id),
        ).fetchall()
        out["candidates"] = [dict(r) for r in rows]
        if not rows:
            out["reason"] = "no_verified_deployment"
            return out
        horizon = occurred_at + self.grace_seconds
        eligible = [
            r for r in rows
            if r["verified_at"] is not None and float(r["verified_at"]) <= horizon
        ]
        if not eligible:
            out["reason"] = "before_first_verified_deployment"
            return out
        top = eligible[0]
        top_at = float(top["verified_at"])
        # 同一时刻的多个 target 若给出不同版本 → 歧义，保持 NULL
        same_moment = [
            r for r in eligible if abs(float(r["verified_at"]) - top_at) <= 1e-6
        ]
        versions = {
            (r["applied_version_id"] if r["applied_version_id"] is not None
             else r["skill_version_id"])
            for r in same_moment
        }
        versions.discard(None)
        out["matched_at"] = top_at
        if not versions:
            out["reason"] = "no_version_in_deployment"
            return out
        if len(versions) != 1:
            out["reason"] = "ambiguous_within_window"
            return out
        out["skill_version_id"] = int(versions.pop())
        out["deployment_id"] = int(top["id"])
        out["reason"] = "deployment_window"
        return out

    def resolve_version(self, skill_id, workspace_id, occurred_at):
        """对外暴露的版本解析诊断入口（事件上报之外的排查用）。"""
        ts = _normalize_ts(occurred_at, "occurred_at", required=True)
        with self._connect() as conn:
            return self._resolve_version_by_window(
                conn, skill_id, (workspace_id or "").strip(), ts
            )

    # ------------------------------------------------------- record_event

    def record_event(self, payload):
        """记录一条加载/应用事件（幂等）。

        返回既有或新建的事件记录（含 `created` 与 `version_resolution`）。
        重复上报 (producer_id, event_key) 时返回既有记录，不新增、不翻倍。
        """
        if not isinstance(payload, dict):
            raise ValidationError("payload must be a dict")

        producer_id = str(payload.get("producer_id") or "").strip()
        if not producer_id:
            raise ValidationError("producer_id is required (idempotency key part 1)")
        event_key = str(payload.get("event_key") or "").strip()
        if not event_key:
            raise ValidationError("event_key is required (idempotency key part 2)")

        event_kind = str(payload.get("event_kind") or "load").strip()
        if event_kind not in EVENT_KINDS:
            raise ValidationError(f"event_kind must be one of {EVENT_KINDS}, got {event_kind!r}")

        # 未声明调用路径一律 unknown：默认 tool 会把 /slug 漏计/错计
        invocation_kind = str(payload.get("invocation_kind") or "unknown").strip()
        if invocation_kind not in INVOCATION_KINDS:
            raise ValidationError(
                f"invocation_kind must be one of {INVOCATION_KINDS}, got {invocation_kind!r}"
            )

        # #668：workspace_id 由调用方解析后传入，本层禁止兜底假值
        workspace_id = str(payload.get("workspace_id") or "").strip()
        if not workspace_id:
            raise ValidationError(
                "workspace_id is required: resolve it per #668 "
                "(DSH_SESSION_ID -> workspace.json) and pass it in; "
                "this module never falls back to a placeholder workspace"
            )

        skill_name = str(payload.get("skill_name") or "").strip()
        if not skill_name and not payload.get("skill_id"):
            raise ValidationError("skill_name or skill_id is required")

        occurred_at = _normalize_ts(payload.get("occurred_at"), "occurred_at", required=True)

        session_id = str(payload.get("session_id") or "")
        turn_id = str(payload.get("turn_id") or "")
        tool_call_id = str(payload.get("tool_call_id") or "")
        run_id = str(payload.get("run_id") or "").strip()
        if not run_id:
            run_id = _run_key(session_id, turn_id)
        observed_content_hash = str(payload.get("observed_content_hash") or "")

        with self._connect() as conn:
            skill_id = self._resolve_skill_id(
                conn, payload.get("skill_id"), skill_name, workspace_id
            )
            if skill_id and not skill_name:
                row = conn.execute("SELECT slug FROM skills WHERE id=?", (skill_id,)).fetchone()
                skill_name = (row["slug"] if row else "") or skill_name

            explicit_version = payload.get("skill_version_id")
            if explicit_version is not None:
                explicit_version = int(explicit_version)
                if not conn.execute(
                    "SELECT 1 FROM skill_versions WHERE id=?", (explicit_version,)
                ).fetchone():
                    raise ValidationError(f"skill_version_id {explicit_version} not found")
                skill_version_id, deployment_id, resolution = explicit_version, None, "explicit"
            else:
                res = self._resolve_version_by_window(
                    conn, skill_id, workspace_id, occurred_at
                )
                skill_version_id = res["skill_version_id"]
                deployment_id = res["deployment_id"]
                resolution = res["reason"]

            cur = conn.execute(
                """
                INSERT INTO skill_usage_events
                  (producer_id, event_key, event_kind, invocation_kind, skill_id,
                   skill_version_id, deployment_id, skill_name, observed_content_hash,
                   session_id, turn_id, tool_call_id, run_id, workspace_id,
                   occurred_at, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(producer_id, event_key) DO NOTHING
                """,
                (
                    producer_id, event_key, event_kind, invocation_kind, skill_id,
                    skill_version_id, deployment_id, skill_name, observed_content_hash,
                    session_id, turn_id, tool_call_id, run_id, workspace_id,
                    occurred_at, _now(),
                ),
            )
            created = cur.rowcount == 1
            row = conn.execute(
                "SELECT * FROM skill_usage_events WHERE producer_id=? AND event_key=?",
                (producer_id, event_key),
            ).fetchone()
        if row is None:  # 理论上不可达：插入或幂等命中必有一行
            raise SkillEventError(
                f"event write/read-back failed for ({producer_id!r}, {event_key!r})"
            )

        record = self._event_to_dict(row)
        record["created"] = created
        record["version_resolution"] = resolution if created else "existing"
        if not created:
            # 幂等命中：暴露与既有记录不一致的字段，便于发现 producer 侧 bug
            diff = []
            for field, value in (
                ("event_kind", event_kind),
                ("invocation_kind", invocation_kind),
                ("skill_name", skill_name),
                ("session_id", session_id),
                ("turn_id", turn_id),
                ("tool_call_id", tool_call_id),
                ("workspace_id", workspace_id),
            ):
                if (record.get(field) or "") != (value or ""):
                    diff.append(field)
            if abs(float(record.get("occurred_at") or 0) - occurred_at) > 1e-6:
                diff.append("occurred_at")
            record["duplicate_diff"] = diff
        return record

    # -------------------------------------------------- record_evaluation

    def record_evaluation(self, payload, require_version=True, dedupe=True):
        """记录一条评价（三源分列，按 kind 校验语义）。

        - `user_rating`: score ∈ [1,5]；`agent_self`: score ∈ [0,1]
        - `task_outcome`: outcome ∈ success|failure|unknown|cancelled，且**必须独立证据**
          （不得携带 score，禁止从 agent 自评分推导）
        - `approval`: decision ∈ approve|reject
        - `require_version=True`（默认）：评价必须绑定版本（方案 §5「评价必须绑定版本」）；
          版本可由 skill_version_id / usage_event_id / run_id 唯一推出，推不出即拒收。
        - `dedupe=True`：应用层按身份字段回读去重（schema 未给 skill_evaluations 建唯一约束，
          此去重是「尽力而为」，不是并发安全保证；重复提交同一评价不会新增行）。
        """
        if not isinstance(payload, dict):
            raise ValidationError("payload must be a dict")

        kind = str(payload.get("kind") or "").strip()
        if kind not in EVALUATION_KINDS:
            raise ValidationError(f"kind must be one of {EVALUATION_KINDS}, got {kind!r}")

        score = payload.get("score")
        outcome = payload.get("outcome")
        decision = payload.get("decision")

        if kind in SCORE_RANGES:
            lo, hi = SCORE_RANGES[kind]
            if score is None:
                raise ValidationError(f"{kind} requires a score within [{lo},{hi}]")
            try:
                score = float(score)
            except (TypeError, ValueError):
                raise ValidationError(f"{kind} score must be numeric, got {payload.get('score')!r}")
            if not (lo <= score <= hi):
                raise ValidationError(f"{kind} score must be within [{lo},{hi}], got {score}")
            if outcome is not None:
                raise ValidationError(f"{kind} must not carry outcome")
            if decision is not None:
                raise ValidationError(f"{kind} must not carry decision")
        elif kind == "task_outcome":
            if outcome not in OUTCOMES:
                raise ValidationError(f"task_outcome requires outcome in {OUTCOMES}, got {outcome!r}")
            if score is not None:
                raise ValidationError(
                    "task_outcome must not carry score: 结果须独立证据，不得从 agent 自评推导"
                )
            if decision is not None:
                raise ValidationError("task_outcome must not carry decision")
        else:  # approval
            if decision not in DECISIONS:
                raise ValidationError(f"approval requires decision in {DECISIONS}, got {decision!r}")
            if score is not None:
                raise ValidationError("approval must not carry score")
            if outcome is not None:
                raise ValidationError("approval must not carry outcome")

        created_at = _normalize_ts(
            payload.get("created_at"), "created_at", required=False, default=_now()
        )

        usage_event_id = payload.get("usage_event_id")
        if usage_event_id is not None:
            usage_event_id = int(usage_event_id)

        reviewer_id = str(payload.get("reviewer_id") or "")
        model_id = str(payload.get("model_id") or "")
        rubric_version = str(payload.get("rubric_version") or "")
        evidence_ref = str(payload.get("evidence_ref") or "")
        comment = str(payload.get("comment") or "")

        with self._connect() as conn:
            ev_row = None
            if usage_event_id is not None:
                ev_row = conn.execute(
                    "SELECT * FROM skill_usage_events WHERE id=?", (usage_event_id,)
                ).fetchone()
                if ev_row is None:
                    raise ValidationError(f"usage_event_id {usage_event_id} not found")

            run_id = str(payload.get("run_id") or "").strip()
            if not run_id and ev_row is not None:
                run_id = (ev_row["run_id"] or "") or _run_key(
                    ev_row["session_id"], ev_row["turn_id"]
                )

            explicit_version = payload.get("skill_version_id")
            if explicit_version is not None:
                skill_version_id = int(explicit_version)
                if not conn.execute(
                    "SELECT 1 FROM skill_versions WHERE id=?", (skill_version_id,)
                ).fetchone():
                    raise ValidationError(f"skill_version_id {skill_version_id} not found")
            elif ev_row is not None and ev_row["skill_version_id"] is not None:
                skill_version_id = int(ev_row["skill_version_id"])
            else:
                skill_version_id = None
                if run_id:
                    rows = conn.execute(
                        "SELECT DISTINCT skill_version_id FROM skill_usage_events"
                        " WHERE run_id=? AND skill_version_id IS NOT NULL",
                        (run_id,),
                    ).fetchall()
                    if len(rows) == 1:
                        skill_version_id = int(rows[0]["skill_version_id"])
                    # 多个版本 → 无法唯一确定，保持 NULL（禁止猜）

            skill_id = str(payload.get("skill_id") or "").strip() or None
            if not skill_id and ev_row is not None and ev_row["skill_id"]:
                skill_id = ev_row["skill_id"]
            if not skill_id and skill_version_id is not None:
                row = conn.execute(
                    "SELECT skill_id FROM skill_versions WHERE id=?", (skill_version_id,)
                ).fetchone()
                skill_id = row["skill_id"] if row else None

            if require_version and skill_version_id is None:
                raise ValidationError(
                    "skill_version_id could not be determined: pass skill_version_id, or "
                    "usage_event_id / run_id that uniquely identifies the observed version; "
                    "评价必须绑定版本（不确定即拒收，禁止按 slug 关联最新版）"
                )

            if dedupe:
                existing = conn.execute(
                    """
                    SELECT * FROM skill_evaluations
                     WHERE kind=?
                       AND IFNULL(skill_version_id,-1)=IFNULL(?,-1)
                       AND IFNULL(usage_event_id,-1)=IFNULL(?,-1)
                       AND run_id=? AND reviewer_id=? AND model_id=?
                       AND IFNULL(score,-1)=IFNULL(?,-1)
                       AND IFNULL(outcome,'')=IFNULL(?,'')
                       AND IFNULL(decision,'')=IFNULL(?,'')
                     ORDER BY id LIMIT 1
                    """,
                    (
                        kind, skill_version_id, usage_event_id, run_id,
                        reviewer_id, model_id, score, outcome, decision,
                    ),
                ).fetchone()
                if existing is not None:
                    rec = self._evaluation_to_dict(existing)
                    rec["created"] = False
                    rec["dedupe"] = "app_layer_identity"
                    return rec

            cur = conn.execute(
                """
                INSERT INTO skill_evaluations
                  (skill_id, skill_version_id, usage_event_id, run_id, kind, reviewer_id,
                   model_id, rubric_version, score, outcome, decision, evidence_ref,
                   comment, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    skill_id, skill_version_id, usage_event_id, run_id, kind, reviewer_id,
                    model_id, rubric_version, score, outcome, decision, evidence_ref,
                    comment, created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM skill_evaluations WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        if row is None:  # 理论上不可达
            raise SkillEventError("evaluation write/read-back failed")

        rec = self._evaluation_to_dict(row)
        rec["created"] = True
        return rec

    # ---------------------------------------------------------------- stats

    def stats(self, skill_id, version_id=None):
        """按 skill（可选版本）汇总加载/应用/效果指标。

        口径（方案 §三「统计口径」）：
        - `load_count`：去重后的加载事件数（跨 producer 逻辑去重）
        - `applied_run_count`：apply 事件的 distinct run_id
        - `effectiveness`：只取「已评价的 distinct run」，`success/(success+failure)`；
          无 success/failure 样本 → None；unknown/cancelled 不算失败
        - `coverage`：被评价的 run 占「观察到 run」的比例；无观察 run → None
        - `by_source`：user_rating / agent_self 分开算均值，**不混合平均**
        """
        if not skill_id:
            raise ValidationError("skill_id is required")
        skill_id = str(skill_id)
        version_id = int(version_id) if version_id is not None else None

        where = "skill_id=?"
        params = [skill_id]
        if version_id is not None:
            where += " AND skill_version_id=?"
            params.append(version_id)

        with self._connect() as conn:
            agg = conn.execute(
                f"SELECT COUNT(*) AS n, MIN(occurred_at) AS first_at,"
                f" MAX(occurred_at) AS last_at,"
                f" SUM(CASE WHEN skill_version_id IS NULL THEN 1 ELSE 0 END) AS unversioned"
                f" FROM skill_usage_events WHERE {where}",
                params,
            ).fetchone()
            load_count = conn.execute(
                f"SELECT COUNT(DISTINCT {_DEDUP_KEY_SQL}) AS n FROM skill_usage_events"
                f" WHERE {where} AND event_kind='load'",
                params,
            ).fetchone()["n"]
            applied_run_count = conn.execute(
                f"SELECT COUNT(DISTINCT run_id) AS n FROM skill_usage_events"
                f" WHERE {where} AND event_kind='apply' AND run_id<>''",
                params,
            ).fetchone()["n"]
            observed_run_ids = {
                r["run_id"] for r in conn.execute(
                    f"SELECT DISTINCT run_id FROM skill_usage_events"
                    f" WHERE {where} AND run_id<>''",
                    params,
                )
            }
            invocation_counts = {"load": {}, "apply": {}}
            for r in conn.execute(
                f"SELECT event_kind, invocation_kind,"
                f" COUNT(DISTINCT {_DEDUP_KEY_SQL}) AS n"
                f" FROM skill_usage_events WHERE {where}"
                f" GROUP BY event_kind, invocation_kind",
                params,
            ):
                invocation_counts.setdefault(r["event_kind"], {})[r["invocation_kind"]] = r["n"]
            versions_seen = [
                {"skill_version_id": r["skill_version_id"], "events": r["n"]}
                for r in conn.execute(
                    f"SELECT skill_version_id, COUNT(*) AS n FROM skill_usage_events"
                    f" WHERE {where} GROUP BY skill_version_id ORDER BY n DESC",
                    params,
                )
            ]

            ev_where = "COALESCE(e.skill_id, ev.skill_id) = ?"
            ev_params = [skill_id]
            if version_id is not None:
                ev_where += " AND COALESCE(e.skill_version_id, ev.skill_version_id) = ?"
                ev_params.append(version_id)
            eval_rows = conn.execute(
                f"""
                SELECT e.id, e.kind, e.score, e.outcome, e.decision, e.reviewer_id,
                       e.model_id, e.run_id AS eval_run_id, e.created_at,
                       ev.run_id AS ev_run_id, ev.session_id, ev.turn_id
                  FROM skill_evaluations e
                  LEFT JOIN skill_usage_events ev ON ev.id = e.usage_event_id
                 WHERE {ev_where}
                 ORDER BY e.created_at, e.id
                """,
                ev_params,
            ).fetchall()

        by_source = {
            "user_rating": {"count": 0, "mean": None, "min": None, "max": None,
                            "distribution": {str(i): 0 for i in range(1, 6)}},
            "agent_self": {"count": 0, "mean": None, "min": None, "max": None},
            "task_outcome": {"evaluations": {o: 0 for o in OUTCOMES}},
            "approval": {d: 0 for d in DECISIONS},
        }
        scores = {"user_rating": [], "agent_self": []}
        evaluated_run_ids = set()
        # run_id → (created_at, id, outcome)：同一 run 多次评价取最新
        per_run_outcome = {}

        for r in eval_rows:
            rid = (r["eval_run_id"] or "").strip() or (r["ev_run_id"] or "").strip() \
                or _run_key(r["session_id"], r["turn_id"])
            if rid:
                evaluated_run_ids.add(rid)
            kind = r["kind"]
            if kind in SCORE_RANGES:
                if r["score"] is not None:
                    scores[kind].append(float(r["score"]))
                    by_source[kind]["count"] += 1
                    if kind == "user_rating":
                        bucket = str(int(round(float(r["score"]))))
                        if bucket in by_source[kind]["distribution"]:
                            by_source[kind]["distribution"][bucket] += 1
            elif kind == "task_outcome":
                by_source["task_outcome"]["evaluations"][r["outcome"]] += 1
                if rid:
                    prev = per_run_outcome.get(rid)
                    stamp = (float(r["created_at"]), int(r["id"]))
                    if prev is None or stamp >= (prev[0], prev[1]):
                        per_run_outcome[rid] = (stamp[0], stamp[1], r["outcome"])
            else:
                by_source["approval"][r["decision"]] += 1

        for kind, values in scores.items():
            if values:
                by_source[kind]["mean"] = round(sum(values) / len(values), 4)
                by_source[kind]["min"] = min(values)
                by_source[kind]["max"] = max(values)

        run_outcomes = {o: 0 for o in OUTCOMES}
        for _, _, outcome in per_run_outcome.values():
            run_outcomes[outcome] += 1

        success = run_outcomes["success"]
        failure = run_outcomes["failure"]
        samples = success + failure
        effectiveness = round(success / samples, 6) if samples else None
        if effectiveness is None:
            if not eval_rows or by_source["task_outcome"]["evaluations"] == {o: 0 for o in OUTCOMES}:
                effectiveness_reason = "no_task_outcome_evaluation"
            else:
                effectiveness_reason = "only_unknown_or_cancelled"
        else:
            effectiveness_reason = None

        evaluated_runs = len(evaluated_run_ids)
        if observed_run_ids:
            coverage = round(len(evaluated_run_ids & observed_run_ids) / len(observed_run_ids), 6)
        else:
            coverage = None

        return {
            "skill_id": skill_id,
            "version_id": version_id,
            "version_scoped": version_id is not None,
            "event_count": agg["n"] or 0,
            "load_count": load_count,
            "applied_run_count": applied_run_count,
            "observed_runs": len(observed_run_ids),
            "evaluated_runs": evaluated_runs,
            "coverage": coverage,
            "effectiveness": effectiveness,
            "effectiveness_samples": samples,
            "effectiveness_reason": effectiveness_reason,
            # 以 distinct run 为口径的结果分布（unknown/cancelled 不计入分母）
            "outcome_counts": run_outcomes,
            # 原始评价行数（用于区分「样本数」与「评价条数」）
            "outcome_evaluations": dict(by_source["task_outcome"]["evaluations"]),
            "invocation_counts": invocation_counts,
            "by_source": by_source,
            "versions_seen": versions_seen,
            "unversioned_events": agg["unversioned"] or 0,
            "window": {
                "first_at": agg["first_at"],
                "last_at": agg["last_at"],
                "first_iso": _iso(agg["first_at"]),
                "last_iso": _iso(agg["last_at"]),
            },
        }

    # ---------------------------------------------------------------- lists

    def list_events(self, skill_id, since=None, k=100, workspace_id=None,
                    version_id=None, event_kind=None):
        """列出事件（occurred_at 倒序）。since 接受秒或毫秒。"""
        if not skill_id:
            raise ValidationError("skill_id is required")
        where = "skill_id=?"
        params = [str(skill_id)]
        if since is not None:
            where += " AND occurred_at >= ?"
            params.append(_normalize_ts(since, "since", required=True))
        if workspace_id is not None:
            where += " AND workspace_id=?"
            params.append(str(workspace_id))
        if version_id is not None:
            where += " AND skill_version_id=?"
            params.append(int(version_id))
        if event_kind is not None:
            if event_kind not in EVENT_KINDS:
                raise ValidationError(f"event_kind must be one of {EVENT_KINDS}")
            where += " AND event_kind=?"
            params.append(event_kind)
        k = int(k or 0)
        if k <= 0:
            return []
        params.append(k)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM skill_usage_events WHERE {where}"
                f" ORDER BY occurred_at DESC, id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._event_to_dict(r) for r in rows]

    def list_evaluations(self, skill_id, since=None, k=100, kind=None, version_id=None):
        """列出评价（created_at 倒序）。"""
        if not skill_id:
            raise ValidationError("skill_id is required")
        where = "COALESCE(e.skill_id, ev.skill_id) = ?"
        params = [str(skill_id)]
        if since is not None:
            where += " AND e.created_at >= ?"
            params.append(_normalize_ts(since, "since", required=True))
        if kind is not None:
            if kind not in EVALUATION_KINDS:
                raise ValidationError(f"kind must be one of {EVALUATION_KINDS}")
            where += " AND e.kind=?"
            params.append(kind)
        if version_id is not None:
            where += " AND COALESCE(e.skill_version_id, ev.skill_version_id) = ?"
            params.append(int(version_id))
        k = int(k or 0)
        if k <= 0:
            return []
        params.append(k)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT e.* FROM skill_evaluations e
                  LEFT JOIN skill_usage_events ev ON ev.id = e.usage_event_id
                 WHERE {where}
                 ORDER BY e.created_at DESC, e.id DESC LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._evaluation_to_dict(r) for r in rows]
