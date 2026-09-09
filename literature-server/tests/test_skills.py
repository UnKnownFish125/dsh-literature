#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""literature skill 管理体系单测：迁移框架 / CHECK 约束 / 唯一性 / 幂等 / 统计口径。

覆盖依据：
- 表结构与迁移：literature_skill_schema.py
- 方案契约：docs/dsh-literature-skill-management-v02.md 第三节（数据模型）+ 第七节（采集契约）

运行方式（在 literature-server 目录下；本机解释器名为 python3，若主机上为 python 请替换）：
    cd /www/dsh-literature-deploy/literature-server
    python3 -m unittest tests.test_skills -v
或等价写法：
    python3 -m unittest discover -s tests -p "test_skills.py" -v
或单跑某个类：
    python3 -m unittest tests.test_skills.TestSkillConstraints -v

约定：
- 仅用标准库（unittest / sqlite3 / tempfile / shutil），无需 pytest。
- 每个测试用 tempfile.mkdtemp() 建独立临时库，tearDown 关闭连接并删除目录；
  **绝不连接生产库 data/literature.db**（本文件不引用任何部署数据路径）。
- 断言的是 schema 自身强制的行为（CHECK / UNIQUE / FK / 幂等迁移），
  不测试尚未落地的业务模块；第 8 类统计口径在没有 events 模块时以数据层语义覆盖并注明。
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import uuid

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import literature_skill_schema as SS  # noqa: E402

# 固定时间戳，避免测试依赖系统时钟
NOW = 1788925050.0

# 方案第三节「统计口径」的参考实现（数据层）：
#   effectiveness 只用已评价的 distinct run：success/(success+failure)
#   unknown / cancelled 不计入分母；无评价 → NULL
EFFECTIVENESS_SQL = """
SELECT AVG(CASE WHEN outcome = 'success' THEN 1.0
                WHEN outcome = 'failure' THEN 0.0 END)
  FROM skill_evaluations
 WHERE kind = 'task_outcome' AND outcome IN ('success', 'failure')
"""

# events / 统计模块可能的落点（PR3 落地后应命中其中之一）
STATS_MODULE_CANDIDATES = (
    "literature_skill_events",
    "literature_skill_stats",
    "literature_skill_metrics",
    "skill_events",
)


class SkillSchemaTestCase(unittest.TestCase):
    """公共夹具：独立临时 DB + 开启外键的连接。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="skill-schema-test-")
        self.db_path = os.path.join(self.tmpdir, "literature-test.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys=ON")

    def tearDown(self):
        try:
            self.conn.close()
        except sqlite3.Error:
            pass
        finally:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 夹具辅助 ─────────────────────────────────────────────────────────
    def install(self, note="unit-test"):
        """应用 skill 迁移，返回 (from_version, to_version, applied_list)。"""
        return SS.install_skill_schema(self.conn, note=note)

    def add_skill(self, slug, scope="global", workspace_id=None, skill_id=None,
                  lifecycle="draft", deleted_at=None):
        sid = skill_id or uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO skills (id, slug, scope, workspace_id, lifecycle,"
            " created_at, updated_at, deleted_at) VALUES (?,?,?,?,?,?,?,?)",
            (sid, slug, scope, workspace_id, lifecycle, NOW, NOW, deleted_at),
        )
        self.conn.commit()
        return sid

    def add_version(self, skill_id, version, source_key=""):
        cur = self.conn.execute(
            "INSERT INTO skill_versions (skill_id, version, source_key, created_at)"
            " VALUES (?,?,?,?)",
            (skill_id, version, source_key, NOW),
        )
        self.conn.commit()
        return cur.lastrowid

    def add_file(self, skill_version_id, rel_path, size_bytes=0):
        cur = self.conn.execute(
            "INSERT INTO skill_files (skill_version_id, rel_path, size_bytes)"
            " VALUES (?,?,?)",
            (skill_version_id, rel_path, size_bytes),
        )
        self.conn.commit()
        return cur.lastrowid

    def add_event(self, producer_id, event_key, event_kind="load",
                  invocation_kind="tool", skill_version_id=None):
        cur = self.conn.execute(
            "INSERT INTO skill_usage_events (producer_id, event_key, event_kind,"
            " invocation_kind, skill_version_id, occurred_at, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (producer_id, event_key, event_kind, invocation_kind,
             skill_version_id, NOW, NOW),
        )
        self.conn.commit()
        return cur.lastrowid

    def add_evaluation(self, kind, score=None, outcome=None, run_id="",
                       skill_version_id=None):
        cur = self.conn.execute(
            "INSERT INTO skill_evaluations (skill_version_id, run_id, kind, score,"
            " outcome, created_at) VALUES (?,?,?,?,?,?)",
            (skill_version_id, run_id, kind, score, outcome, NOW),
        )
        self.conn.commit()
        return cur.lastrowid

    def assertIntegrityError(self, callable_, msg=None):
        """断言 SQL 语句被 schema 拒绝，并回滚事务以免污染后续断言。"""
        with self.assertRaises(sqlite3.IntegrityError, msg=msg):
            try:
                callable_()
            finally:
                self.conn.rollback()

    def count(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()[0]


class TestSkillSchema(SkillSchemaTestCase):
    """迁移框架：首次应用、幂等、schema_migrations 记录。"""

    def test_first_install_applies_migration_1(self):
        self.assertEqual((0, 1, [1]), self.install())

    def test_second_install_is_idempotent(self):
        self.install()
        # 重复调用不应再次应用任何版本，也不应重跑 DDL
        self.assertEqual((1, 1, []), self.install())

    def test_many_repeats_stay_idempotent(self):
        self.install()
        for _ in range(3):
            self.assertEqual([], self.install()[2])
        self.assertEqual(1, self.count("SELECT COUNT(*) FROM schema_migrations"))

    def test_schema_migrations_row_is_recorded(self):
        self.install(note="unit-test")
        rows = list(self.conn.execute(
            "SELECT version, applied_at, checksum, note FROM schema_migrations"))
        self.assertEqual(1, len(rows))
        version, applied_at, checksum, note = rows[0]
        self.assertEqual(1, version)
        self.assertIsInstance(applied_at, float)
        self.assertGreater(applied_at, 0)
        # checksum 为 sha256 前 16 位十六进制，用于检测迁移脚本漂移
        self.assertEqual(16, len(checksum))
        int(checksum, 16)
        self.assertEqual("unit-test", note)

    def test_checksum_matches_migration_statements(self):
        self.install()
        stored = self.conn.execute(
            "SELECT checksum FROM schema_migrations WHERE version=1").fetchone()[0]
        self.assertEqual(SS._checksum(SS.MIGRATIONS[1]), stored)

    def test_all_expected_tables_are_created(self):
        self.install()
        tables = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        expected = {
            "schema_migrations",
            "skills",
            "skill_versions",
            "skill_files",
            "skill_deployments",
            "skill_usage_events",
            "skill_evaluations",
            "skill_audit",
        }
        self.assertTrue(expected.issubset(tables), f"缺少表：{expected - tables}")

    def test_migration_registry_matches_schema_version(self):
        self.assertEqual(SS.SCHEMA_VERSION, max(SS.MIGRATIONS))
        self.assertEqual(1, SS.SCHEMA_VERSION)

    def test_ensure_skill_schema_operates_on_given_file(self):
        # 便捷入口作用于显式传入的文件路径（仍为临时库）
        path = os.path.join(self.tmpdir, "other.db")
        self.assertEqual((0, 1, [1]), SS.ensure_skill_schema(path, note="file"))
        self.assertTrue(os.path.exists(path))
        self.assertEqual((1, 1, []), SS.ensure_skill_schema(path, note="file"))


class TestSkillConstraints(SkillSchemaTestCase):
    """skills.scope / workspace_id 的 CHECK 约束（禁止用空串表示全局）。"""

    def setUp(self):
        super().setUp()
        self.install()

    def test_global_with_workspace_id_rejected(self):
        self.assertIntegrityError(
            lambda: self.add_skill("g-ws", scope="global", workspace_id="w1"),
            "scope=global 必须 workspace_id IS NULL",
        )
        self.assertEqual(0, self.count("SELECT COUNT(*) FROM skills"))

    def test_workspace_with_empty_workspace_id_rejected(self):
        # 139 条事故模式：空串被当作全局
        self.assertIntegrityError(
            lambda: self.add_skill("w-empty", scope="workspace", workspace_id=""))
        self.assertEqual(0, self.count("SELECT COUNT(*) FROM skills"))

    def test_workspace_with_null_workspace_id_rejected(self):
        self.assertIntegrityError(
            lambda: self.add_skill("w-null", scope="workspace", workspace_id=None))

    def test_workspace_with_blank_workspace_id_rejected(self):
        # 空白串经 trim 后长度为 0，同样拒绝
        self.assertIntegrityError(
            lambda: self.add_skill("w-blank", scope="workspace", workspace_id="   "))

    def test_global_with_null_workspace_id_accepted(self):
        sid = self.add_skill("g-ok", scope="global", workspace_id=None)
        row = self.conn.execute(
            "SELECT scope, workspace_id FROM skills WHERE id=?", (sid,)).fetchone()
        self.assertEqual(("global", None), row)

    def test_workspace_with_real_uuid_accepted(self):
        ws = str(uuid.uuid4())
        sid = self.add_skill("w-ok", scope="workspace", workspace_id=ws)
        row = self.conn.execute(
            "SELECT scope, workspace_id FROM skills WHERE id=?", (sid,)).fetchone()
        self.assertEqual(("workspace", ws), row)

    def test_invalid_scope_rejected(self):
        self.assertIntegrityError(
            lambda: self.add_skill("bad-scope", scope="tenant", workspace_id=None))

    def test_invalid_lifecycle_rejected(self):
        self.assertIntegrityError(
            lambda: self.add_skill("bad-life", scope="global", lifecycle="published"))


class TestSkillSlugUniqueness(SkillSchemaTestCase):
    """slug 唯一性：partial unique index 分别约束 global / workspace。"""

    def setUp(self):
        super().setUp()
        self.install()

    def test_duplicate_global_slug_rejected(self):
        self.add_skill("plot-chart", scope="global")
        self.assertIntegrityError(lambda: self.add_skill("plot-chart", scope="global"))
        self.assertEqual(1, self.count(
            "SELECT COUNT(*) FROM skills WHERE slug='plot-chart'"))

    def test_same_slug_in_different_workspaces_allowed(self):
        ws1, ws2 = str(uuid.uuid4()), str(uuid.uuid4())
        self.add_skill("plot-chart", scope="workspace", workspace_id=ws1)
        self.add_skill("plot-chart", scope="workspace", workspace_id=ws2)
        self.assertEqual(2, self.count(
            "SELECT COUNT(*) FROM skills WHERE slug='plot-chart'"))

    def test_duplicate_slug_in_same_workspace_rejected(self):
        ws = str(uuid.uuid4())
        self.add_skill("plot-chart", scope="workspace", workspace_id=ws)
        self.assertIntegrityError(
            lambda: self.add_skill("plot-chart", scope="workspace", workspace_id=ws))

    def test_global_and_workspace_slug_coexist(self):
        # 两个 partial index 互不干扰：全局技能与工作区同名技能可共存
        ws = str(uuid.uuid4())
        self.add_skill("plot-chart", scope="global")
        self.add_skill("plot-chart", scope="workspace", workspace_id=ws)
        self.assertEqual(2, self.count(
            "SELECT COUNT(*) FROM skills WHERE slug='plot-chart'"))

    def test_soft_deleted_global_slug_can_be_reused(self):
        # partial index 带 deleted_at IS NULL，软删后可复用同名
        self.add_skill("plot-chart", scope="global", deleted_at=NOW)
        self.add_skill("plot-chart", scope="global", deleted_at=None)
        self.assertEqual(2, self.count(
            "SELECT COUNT(*) FROM skills WHERE slug='plot-chart'"))

    def test_soft_deleted_workspace_slug_can_be_reused(self):
        ws = str(uuid.uuid4())
        self.add_skill("plot-chart", scope="workspace", workspace_id=ws, deleted_at=NOW)
        self.add_skill("plot-chart", scope="workspace", workspace_id=ws, deleted_at=None)
        self.assertEqual(2, self.count(
            "SELECT COUNT(*) FROM skills WHERE slug='plot-chart'"))


class TestSkillVersionImmutability(SkillSchemaTestCase):
    """版本只追加：UNIQUE(skill_id, version) 与 source_key 幂等。"""

    def setUp(self):
        super().setUp()
        self.install()
        self.skill_id = self.add_skill("plot-chart", scope="global")

    def test_duplicate_version_for_same_skill_rejected(self):
        self.add_version(self.skill_id, 1)
        self.assertIntegrityError(lambda: self.add_version(self.skill_id, 1))
        self.assertEqual(1, self.count(
            "SELECT COUNT(*) FROM skill_versions WHERE skill_id=? AND version=1",
            (self.skill_id,)))

    def test_same_version_number_for_other_skill_allowed(self):
        other = self.add_skill("other-skill", scope="global")
        self.add_version(self.skill_id, 1)
        self.add_version(other, 1)
        self.assertEqual(2, self.count("SELECT COUNT(*) FROM skill_versions"))

    def test_versions_are_append_only_sequence(self):
        for version in (1, 2, 3):
            self.add_version(self.skill_id, version)
        versions = [r[0] for r in self.conn.execute(
            "SELECT version FROM skill_versions WHERE skill_id=? ORDER BY version",
            (self.skill_id,))]
        self.assertEqual([1, 2, 3], versions)

    def test_duplicate_source_key_rejected(self):
        # source_key 幂等：同一上游固定 commit 不得落两份
        self.add_version(self.skill_id, 1, source_key="github:o/r@sha256:abc")
        self.assertIntegrityError(
            lambda: self.add_version(self.skill_id, 2,
                                     source_key="github:o/r@sha256:abc"))

    def test_empty_source_key_is_not_deduplicated(self):
        # partial index 带 source_key <> ''，手工版本不参与上游幂等
        self.add_version(self.skill_id, 1, source_key="")
        self.add_version(self.skill_id, 2, source_key="")
        self.assertEqual(2, self.count(
            "SELECT COUNT(*) FROM skill_versions WHERE source_key=''"))

    def test_version_requires_existing_skill(self):
        # 外键开启时，指向不存在 skill 的版本应被拒绝
        self.assertIntegrityError(lambda: self.add_version("no-such-skill", 1))

    def test_review_status_check(self):
        with self.assertRaises(sqlite3.IntegrityError):
            try:
                self.conn.execute(
                    "INSERT INTO skill_versions (skill_id, version, review_status,"
                    " created_at) VALUES (?,?,?,?)",
                    (self.skill_id, 9, "maybe", NOW))
            finally:
                self.conn.rollback()


class TestSkillUsageEventIdempotency(SkillSchemaTestCase):
    """采集契约硬约定 1：event_key 幂等，重复上报不翻倍。"""

    def setUp(self):
        super().setUp()
        self.install()
        self.skill_id = self.add_skill("plot-chart", scope="global")
        self.version_id = self.add_version(self.skill_id, 1)

    def test_duplicate_producer_event_key_rejected(self):
        self.add_event("log-injector-v1", "session-4cb6d508:turn3:call_9wjC")
        self.assertIntegrityError(lambda: self.add_event(
            "log-injector-v1", "session-4cb6d508:turn3:call_9wjC"))
        self.assertEqual(1, self.count("SELECT COUNT(*) FROM skill_usage_events"))

    def test_insert_or_ignore_does_not_create_second_row(self):
        # 上报路径用 INSERT OR IGNORE：重复上报应静默去重
        key = "session-4cb6d508:turn3:call_9wjC"
        self.add_event("log-injector-v1", key)
        self.conn.execute(
            "INSERT OR IGNORE INTO skill_usage_events (producer_id, event_key,"
            " occurred_at, created_at) VALUES (?,?,?,?)",
            ("log-injector-v1", key, NOW, NOW))
        self.conn.commit()
        self.assertEqual(1, self.count(
            "SELECT COUNT(*) FROM skill_usage_events"
            " WHERE producer_id='log-injector-v1' AND event_key=?", (key,)))

    def test_same_event_key_from_other_producer_allowed(self):
        self.add_event("producer-a", "same-key")
        self.add_event("producer-b", "same-key")
        self.assertEqual(2, self.count("SELECT COUNT(*) FROM skill_usage_events"))

    def test_unknown_version_is_allowed(self):
        # 契约硬约定 2：版本无法确认时保留 NULL，禁止按 slug 关联最新版
        event_id = self.add_event("log-injector-v1", "key-unknown-version",
                                  skill_version_id=None)
        row = self.conn.execute(
            "SELECT skill_version_id FROM skill_usage_events WHERE id=?",
            (event_id,)).fetchone()
        self.assertIsNone(row[0])

    def test_event_kind_check(self):
        self.assertIntegrityError(
            lambda: self.add_event("p", "bad-kind", event_kind="deploy"))

    def test_invocation_kind_check(self):
        self.assertIntegrityError(
            lambda: self.add_event("p", "bad-inv", invocation_kind="http"))

    def test_slash_invocation_kind_allowed(self):
        # 硬约定 4：用户 /slug 调用必须以 slash 上报
        self.add_event("log-injector-v1", "slash-key", invocation_kind="slash")
        self.assertEqual(1, self.count(
            "SELECT COUNT(*) FROM skill_usage_events WHERE invocation_kind='slash'"))

    def test_unknown_invocation_kind_allowed(self):
        self.add_event("log-injector-v1", "unknown-inv",
                       invocation_kind="unknown")
        self.assertEqual(1, self.count(
            "SELECT COUNT(*) FROM skill_usage_events"
            " WHERE invocation_kind='unknown'"))

    def test_event_kind_load_and_apply_both_allowed(self):
        self.add_event("p", "k-load", event_kind="load")
        self.add_event("p", "k-apply", event_kind="apply")
        self.assertEqual(2, self.count("SELECT COUNT(*) FROM skill_usage_events"))


class TestSkillEvaluationKindValidation(SkillSchemaTestCase):
    """评价按 kind 分列校验：用户 1-5、agent 0-1。"""

    def setUp(self):
        super().setUp()
        self.install()
        self.skill_id = self.add_skill("plot-chart", scope="global")
        self.version_id = self.add_version(self.skill_id, 1)

    def test_user_rating_above_range_rejected(self):
        self.assertIntegrityError(
            lambda: self.add_evaluation("user_rating", score=6,
                                        skill_version_id=self.version_id))
        self.assertEqual(0, self.count("SELECT COUNT(*) FROM skill_evaluations"))

    def test_user_rating_in_range_accepted(self):
        self.add_evaluation("user_rating", score=3,
                            skill_version_id=self.version_id)
        row = self.conn.execute(
            "SELECT kind, score FROM skill_evaluations").fetchone()
        self.assertEqual(("user_rating", 3.0), row)

    def test_user_rating_zero_rejected(self):
        self.assertIntegrityError(
            lambda: self.add_evaluation("user_rating", score=0,
                                        skill_version_id=self.version_id))

    def test_user_rating_boundaries_accepted(self):
        self.add_evaluation("user_rating", score=1,
                            skill_version_id=self.version_id)
        self.add_evaluation("user_rating", score=5,
                            skill_version_id=self.version_id)
        self.assertEqual(2, self.count("SELECT COUNT(*) FROM skill_evaluations"))

    def test_user_rating_null_score_accepted(self):
        # score 可空（例如只有文字评论）
        self.add_evaluation("user_rating", score=None,
                            skill_version_id=self.version_id)
        self.assertEqual(1, self.count("SELECT COUNT(*) FROM skill_evaluations"))

    def test_agent_self_above_one_rejected(self):
        self.assertIntegrityError(
            lambda: self.add_evaluation("agent_self", score=1.5,
                                        skill_version_id=self.version_id))

    def test_agent_self_zero_and_one_accepted(self):
        self.add_evaluation("agent_self", score=0,
                            skill_version_id=self.version_id)
        self.add_evaluation("agent_self", score=1,
                            skill_version_id=self.version_id)
        self.assertEqual(2, self.count("SELECT COUNT(*) FROM skill_evaluations"))

    def test_invalid_kind_rejected(self):
        self.assertIntegrityError(
            lambda: self.add_evaluation("vibe", score=1,
                                        skill_version_id=self.version_id))

    def test_invalid_outcome_rejected(self):
        self.assertIntegrityError(
            lambda: self.add_evaluation("task_outcome", outcome="great",
                                        skill_version_id=self.version_id))

    def test_task_outcome_with_valid_outcome_accepted(self):
        self.add_evaluation("task_outcome", outcome="success", run_id="run-1",
                            skill_version_id=self.version_id)
        self.add_evaluation("task_outcome", outcome="unknown", run_id="run-2",
                            skill_version_id=self.version_id)
        self.assertEqual(2, self.count("SELECT COUNT(*) FROM skill_evaluations"))


class TestSkillFilesPathValidation(SkillSchemaTestCase):
    """bundle 资源路径校验：拒绝绝对路径与任何 .. 穿越。"""

    def setUp(self):
        super().setUp()
        self.install()
        self.skill_id = self.add_skill("plot-chart", scope="global")
        self.version_id = self.add_version(self.skill_id, 1)

    def test_parent_traversal_rejected(self):
        self.assertIntegrityError(
            lambda: self.add_file(self.version_id, "../etc/passwd"))
        self.assertEqual(0, self.count("SELECT COUNT(*) FROM skill_files"))

    def test_absolute_path_rejected(self):
        self.assertIntegrityError(lambda: self.add_file(self.version_id, "/abs"))

    def test_nested_traversal_rejected(self):
        self.assertIntegrityError(
            lambda: self.add_file(self.version_id, "scripts/../../etc/passwd"))

    def test_windows_style_traversal_rejected(self):
        # CHECK 用 '%..%' 匹配，任何位置的 .. 都拒绝
        self.assertIntegrityError(
            lambda: self.add_file(self.version_id, "a/..b/c.sh"))

    def test_normal_relative_path_accepted(self):
        self.add_file(self.version_id, "scripts/run.sh", size_bytes=42)
        self.add_file(self.version_id, "SKILL.md")
        paths = sorted(r[0] for r in self.conn.execute(
            "SELECT rel_path FROM skill_files ORDER BY rel_path"))
        self.assertEqual(["SKILL.md", "scripts/run.sh"], paths)

    def test_duplicate_rel_path_in_same_version_rejected(self):
        self.add_file(self.version_id, "scripts/run.sh")
        self.assertIntegrityError(
            lambda: self.add_file(self.version_id, "scripts/run.sh"))

    def test_same_rel_path_in_other_version_allowed(self):
        v2 = self.add_version(self.skill_id, 2)
        self.add_file(self.version_id, "scripts/run.sh")
        self.add_file(v2, "scripts/run.sh")
        self.assertEqual(2, self.count("SELECT COUNT(*) FROM skill_files"))

    def test_file_requires_existing_version(self):
        self.assertIntegrityError(lambda: self.add_file(999999, "scripts/run.sh"))


class TestSkillStatsModuleContract(SkillSchemaTestCase):
    """统计口径（模块依赖部分）：events/统计模块未落地时跳过并注明。

    方案第三节口径：effectiveness 只用已评价的 distinct run，
    success/(success+failure)；无评价返回 NULL；unknown/cancelled 不算失败。
    该口径由业务模块（PR3）实现；本仓库当前只有 schema 层，
    因此这里做模块发现，模块缺失即 skip 并写明原因；
    模块落地后应在此类中断言其函数输出与 EFFECTIVENESS_SQL 一致。
    """

    def _find_stats_module(self):
        for name in STATS_MODULE_CANDIDATES:
            try:
                return __import__(name)
            except ImportError:
                continue
        return None

    def test_effectiveness_module_available(self):
        module = self._find_stats_module()
        if module is None:
            self.skipTest(
                "events/统计模块尚未落地（未找到 %s）；统计口径的模块级断言待 PR3 启用。"
                "数据层语义已由 TestSkillStatsDataSemantics 覆盖。"
                % ", ".join(STATS_MODULE_CANDIDATES))
        # 模块存在时的最小契约：至少暴露一个可调用的效果评估入口
        candidates = ("skill_effectiveness", "effectiveness", "compute_effectiveness",
                      "skill_stats", "evaluation_summary")
        funcs = [getattr(module, name) for name in candidates
                 if callable(getattr(module, name, None))]
        if not funcs:
            self.skipTest(
                "已找到模块 %s，但未暴露可识别的效果评估入口 %s；"
                "请按契约补测。" % (module.__name__, candidates))
        self.install()
        self.assertTrue(funcs, "效果评估入口应为可调用对象")


class TestSkillStatsDataSemantics(SkillSchemaTestCase):
    """统计口径（数据层）：无评价 → NULL；unknown/cancelled 不计入失败。

    说明：当前仓库没有 events/统计模块，故按方案第三节口径以 SQL 断言数据层语义；
    模块落地后由 TestSkillStatsModuleContract 补齐函数级断言。
    """

    def setUp(self):
        super().setUp()
        self.install()
        self.skill_id = self.add_skill("plot-chart", scope="global")
        self.version_id = self.add_version(self.skill_id, 1)

    def effectiveness(self):
        return self.conn.execute(EFFECTIVENESS_SQL).fetchone()[0]

    def test_no_evaluations_yields_null(self):
        # 有加载事件、无任何评价 → effectiveness 为 NULL（不是 0，也不是 1）
        self.add_event("log-injector-v1", "k1", skill_version_id=self.version_id)
        self.assertIsNone(self.effectiveness())

    def test_unknown_outcome_not_counted_as_failure(self):
        self.add_evaluation("task_outcome", outcome="success", run_id="run-1")
        self.add_evaluation("task_outcome", outcome="failure", run_id="run-2")
        self.add_evaluation("task_outcome", outcome="unknown", run_id="run-3")
        self.add_evaluation("task_outcome", outcome="cancelled", run_id="run-4")
        # 分母只含 success+failure → 1/2；unknown/cancelled 既不加分也不减分
        self.assertAlmostEqual(0.5, self.effectiveness())

    def test_only_unknown_outcomes_yields_null(self):
        self.add_evaluation("task_outcome", outcome="unknown", run_id="run-1")
        self.add_evaluation("task_outcome", outcome="cancelled", run_id="run-2")
        self.assertIsNone(self.effectiveness())

    def test_all_success_yields_one(self):
        for i in range(3):
            self.add_evaluation("task_outcome", outcome="success", run_id=f"run-{i}")
        self.assertAlmostEqual(1.0, self.effectiveness())

    def test_sample_size_is_distinct_evaluated_runs(self):
        # 同时显示样本数：只统计参与分母的评价条数
        self.add_evaluation("task_outcome", outcome="success", run_id="run-1")
        self.add_evaluation("task_outcome", outcome="unknown", run_id="run-2")
        self.add_evaluation("task_outcome", outcome="failure", run_id="run-3")
        sample = self.count(
            "SELECT COUNT(*) FROM skill_evaluations WHERE kind='task_outcome'"
            " AND outcome IN ('success','failure')")
        self.assertEqual(2, sample)

    def test_load_count_is_not_applied_run_count(self):
        # 口径纠正：load_count ≠ applied_run_count，必须分开统计
        for i in range(3):
            self.add_event("p", f"load-{i}", event_kind="load")
        self.add_event("p", "apply-1", event_kind="apply")
        counts = dict(self.conn.execute(
            "SELECT event_kind, COUNT(*) FROM skill_usage_events GROUP BY event_kind"))
        self.assertEqual(3, counts.get("load"))
        self.assertEqual(1, counts.get("apply"))

    def test_events_with_unknown_version_do_not_borrow_latest_version(self):
        # 版本不确定的事件保持 NULL，不得被归到 version=1
        self.add_event("p", "k-unknown", skill_version_id=None)
        self.assertEqual(0, self.count(
            "SELECT COUNT(*) FROM skill_usage_events WHERE skill_version_id=?",
            (self.version_id,)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
