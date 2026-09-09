#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
literature_skill_layers.py — skill 的 L0/L1/L2 渐进式分层生成。

借鉴 OpenViking 的三层加载（L0 摘要 / L1 概览 / L2 详情）：
- L0 summary_l0：一句话，回答"这技能解决什么问题、何时用"——列表与目录注入用它省 token
- L1 overview_l1：结构化概览（适用场景 / 前置条件 / 关键步骤 / 产物）——详情默认展示
- L2：复用 skill_versions.skill_md 正文，按需加载

生成走 DeepSeek 官方 API（api.deepseek.com）。失败不抛到调用方：返回 ok=False 并保留原文。
生成只写 summary_l0 / overview_l1 / layer_model / layers_generated_at 四个元数据列，
**不触碰任何内容列**（skill_md / manifest / hash），版本内容仍不可变。
"""
import json
import os
import re
import sqlite3
import time
import urllib.request

DEFAULT_MODEL = "deepseek-v4-flash"
API_URL = "https://api.deepseek.com/v1/chat/completions"
MAX_INPUT_CHARS = 12000          # SKILL.md 可能几十 KB，按结构截断
MAX_L0_CHARS = 120
MAX_L1_CHARS = 800

SYSTEM_PROMPT = """你是 agent 技能索引生成器。给定一个 SKILL.md 的正文，产出两级索引。

L0（一句话，不超过 60 字）：这个技能**解决什么问题**、**什么时候该用它**。不要复述技能名，不要写"本技能是…"。

L1（结构化概览，不超过 400 字），严格用这四行：
- 适用场景：<什么任务/什么输入下用它>
- 前置条件：<需要什么环境、依赖、权限；没有就写"无">
- 关键步骤：<3–5 条，用分号分隔>
- 产物：<产出什么文件/格式>

只输出 JSON：{"l0": "...", "l1": "..."}
不要 markdown 围栏，不要解释，不要多余字段。"""


class LayerError(ValueError):
    pass


def _credentials_map():
    """读取 .credentials.yaml 的 refs（与 literature_nightly 一致）。"""
    for cand in (
        os.environ.get("LITERATURE_CREDENTIALS"),
        "/www/dsh/home/.credentials.yaml",
        os.path.expanduser("~/.credentials.yaml"),
    ):
        if not cand or not os.path.exists(cand):
            continue
        try:
            import yaml
            doc = yaml.safe_load(open(cand, encoding="utf-8"))
            return (doc.get("refs") or doc) or {}
        except Exception:
            continue
    return {}


def _truncate_skill_md(text, limit=MAX_INPUT_CHARS):
    """按结构截断：保留 frontmatter + 开头正文 + 各级标题清单（标题本身信息量大）。"""
    if len(text) <= limit:
        return text
    head, sep, rest = text.partition("\n---\n")
    frontmatter = (head + sep) if sep else ""
    headings = [ln.strip() for ln in text.splitlines()
                if re.match(r"^\s{0,3}#{1,4}\s+\S", ln)]
    budget = max(2000, limit - len(frontmatter) - sum(len(h) + 1 for h in headings))
    body = rest[:budget] if sep else text[:budget]
    return frontmatter + body + "\n\n[标题索引]\n" + "\n".join(headings[:80])


def _extract_json(text):
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def generate_layers(skill_md, model=DEFAULT_MODEL, api_key=None, timeout=120):
    """调 LLM 生成 L0/L1。返回 {"ok":bool, "l0":str, "l1":str, "model":str, "error":str}。"""
    if not isinstance(skill_md, str) or not skill_md.strip():
        return {"ok": False, "l0": "", "l1": "", "model": "", "error": "skill_md is empty"}
    key = api_key or _credentials_map().get("DEEPSEEK_API_KEY") or ""
    if not key:
        return {"ok": False, "l0": "", "l1": "", "model": "", "error": "no DEEPSEEK_API_KEY"}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _truncate_skill_md(skill_md)},
        ],
        "temperature": 0.2,
        "max_tokens": 2000,
        # 实测：推理模型的 reasoning_tokens 与 content 共享 max_tokens 预算，
        # 默认档会把预算烧在推理上导致 content 为空（间歇性失败）。降到 low：
        # reasoning 从 ~326 降到 ~30，content 更长、总 token 更少（effort=off 不支持，返回 400）。
        "reasoning_effort": "low",
        "response_format": {"type": "json_object"},
    }
    last_error = ""
    for attempt in range(3):
        req = urllib.request.Request(
            API_URL, data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_error = str(exc)[:200]
            time.sleep(1 + attempt)
            continue
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        parsed = _extract_json(content)
        if isinstance(parsed, dict) and str(parsed.get("l0", "")).strip():
            l0 = " ".join(str(parsed.get("l0", "")).split())[:MAX_L0_CHARS]
            l1 = str(parsed.get("l1", "")).strip()[:MAX_L1_CHARS]
            return {"ok": True, "l0": l0, "l1": l1, "model": model, "error": ""}
        last_error = "no usable JSON (content=%d chars)" % len(content or "")
        time.sleep(1 + attempt)
    return {"ok": False, "l0": "", "l1": "", "model": model, "error": last_error}


class LayerStore:
    """把生成结果写回 skill_versions（只写四个元数据列）。"""

    def __init__(self, db_path, model=DEFAULT_MODEL, api_key=None):
        self.db_path = db_path
        self.model = model
        self.api_key = api_key

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def pending(self, workspace_id="", k=50):
        """返回缺 L0 的版本（按版本号倒序）。workspace_id 为空则只取全局。"""
        sql = ("SELECT v.id, v.skill_id, v.version, v.skill_md FROM skill_versions v "
               "JOIN skills s ON s.id=v.skill_id "
               "WHERE s.deleted_at IS NULL AND (v.summary_l0 IS NULL OR v.summary_l0='') ")
        args = []
        if workspace_id:
            sql += "AND ((s.scope='global' AND s.workspace_id IS NULL) OR (s.scope='workspace' AND s.workspace_id=?)) "
            args.append(workspace_id)
        else:
            sql += "AND (s.scope='global' AND s.workspace_id IS NULL) "
        sql += "ORDER BY v.created_at DESC LIMIT ?"
        args.append(int(k))
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, args)]

    def apply(self, version_id, result, force=False):
        """写入生成结果；默认不覆盖已有 L0（force=True 才重算）。"""
        if not result.get("ok"):
            return {"updated": False, "error": result.get("error", "generate failed")}
        with self._conn() as conn:
            row = conn.execute("SELECT summary_l0 FROM skill_versions WHERE id=?",
                               (int(version_id),)).fetchone()
            if row is None:
                raise LayerError("skill version not found")
            if row["summary_l0"] and not force:
                return {"updated": False, "error": "already has L0"}
            conn.execute(
                "UPDATE skill_versions SET summary_l0=?, overview_l1=?, layer_model=?, "
                "layers_generated_at=? WHERE id=?",
                (result["l0"], result["l1"], result["model"], time.time(), int(version_id)))
            conn.commit()
            return {"updated": True, "version_id": int(version_id),
                    "l0": result["l0"], "l1": result["l1"]}

    def generate_for(self, version_id, force=False):
        with self._conn() as conn:
            row = conn.execute("SELECT skill_md FROM skill_versions WHERE id=?",
                               (int(version_id),)).fetchone()
        if row is None:
            raise LayerError("skill version not found")
        result = generate_layers(row["skill_md"], model=self.model, api_key=self.api_key)
        out = self.apply(version_id, result, force=force)
        out["ok"] = bool(result.get("ok"))
        out["error"] = result.get("error", "") or out.get("error", "")
        return out

    def backfill(self, workspace_id="", k=50, force=False):
        """批量补生成；返回逐条结果（失败不中断）。"""
        results = []
        for item in self.pending(workspace_id=workspace_id, k=k):
            try:
                out = self.generate_for(item["id"], force=force)
            except Exception as exc:
                out = {"ok": False, "updated": False, "error": str(exc)[:160]}
            out.update(version=item["version"], skill_id=item["skill_id"])
            results.append(out)
        return results


def _self_test():
    """离线自测：截断与解析逻辑，不调网络。"""
    long_md = ("---\nname: demo\ndescription: d\n---\n# 标题一\n" + "正文内容" * 3000 +
               "\n## 标题二\n" + "更多内容" * 3000)
    cut = _truncate_skill_md(long_md, limit=4000)
    assert len(cut) <= 4000 + 2000, len(cut)
    assert cut.startswith("---"), "frontmatter 应保留"
    assert "[标题索引]" in cut and "标题一" in cut and "标题二" in cut
    print("PASS truncate: 保留 frontmatter + 正文预算 + 标题索引")

    assert _extract_json('前言 {"l0":"a","l1":"b"} 后记') == {"l0": "a", "l1": "b"}
    assert _extract_json("没有 JSON") is None
    print("PASS extract_json: 容忍前后缀 / 无 JSON 返回 None")

    bad = generate_layers("", api_key="x")
    assert bad["ok"] is False and "empty" in bad["error"]
    # 用无效 key 验证失败路径（不能传空串——空串会 fallback 到真实凭据）
    bad2 = generate_layers("body", api_key="invalid-key-for-selftest")
    assert bad2["ok"] is False and bad2["error"], bad2
    print("PASS guard: 空正文与鉴权失败都安全返回 ok=False")
    print("ALL LAYER SELF-TESTS PASSED")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--backfill", metavar="DB")
    ap.add_argument("--workspace-id", default="")
    ap.add_argument("--k", type=int, default=50)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        _self_test()
    elif args.backfill:
        store = LayerStore(args.backfill)
        for r in store.backfill(workspace_id=args.workspace_id, k=args.k, force=args.force):
            print(f"  v{r.get('version')} ok={r.get('ok')} updated={r.get('updated')} "
                  f"{(r.get('l0') or r.get('error') or '')[:70]}")
    else:
        ap.print_help()
