#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_server_dispatch_order.py — 分发顺序回归测试。

背景（2026-09-16 实测缺陷）：skill 路由（SKILL_ROUTES.try_handle）曾插在 do_GET
的 `_reject_browser_origin()` **之前**。后者同时负责「拒浏览器 Origin(403)」与
「校验 Bearer(401)」，因此该顺序让 `GET /v1/skills`、`/v1/skill-deployments` 等读路由
**完全绕过鉴权**——任何本机可访问者都能读取技能元数据。

本测试对 server 源码做**静态顺序断言**，确保 hook 永远排在鉴权之后；不依赖服务启动。
技能路由若要在其他方法里加 hook，同样受此约束。
"""
import os
import re
import unittest

SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "literature_server.py")

# 鉴权入口的多种写法都算（避免有人改名后测试失效）
AUTH_MARKERS = ("_reject_browser_origin",)
HOOK_MARKERS = ("SKILL_ROUTES.try_handle",)


def _method_body(source, method):
    """截取 `def <method>(self)` 到下一个同级 `def` 之间的源码。"""
    pattern = re.compile(
        r"\n    def %s\(self\).*?(?=\n    def |\nclass |\Z)" % re.escape(method), re.S)
    match = pattern.search(source)
    if not match:
        raise AssertionError("未找到方法: %s" % method)
    return match.group(0)


class TestDispatchOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SERVER, encoding="utf-8") as fh:
            cls.source = fh.read()

    def _assert_auth_before_hook(self, method):
        body = _method_body(self.source, method)
        hook_pos = min((body.find(m) for m in HOOK_MARKERS if m in body), default=-1)
        if hook_pos < 0:
            self.skipTest("%s 未挂载 skill hook（无需检查顺序）" % method)
        auth_pos = min((body.find(m) for m in AUTH_MARKERS if m in body), default=-1)
        self.assertGreaterEqual(
            auth_pos, 0,
            "%s 里挂了 skill hook 但找不到鉴权入口 %s —— 鉴权被移除或改名了"
            % (method, AUTH_MARKERS))
        self.assertLess(
            auth_pos, hook_pos,
            "%s 的 skill hook 出现在鉴权之前（第 %d 字符 vs 第 %d 字符）："
            "这会让读路由绕过 401/403。请把 try_handle 移到 _reject_browser_origin 之后。"
            % (method, hook_pos, auth_pos))

    def test_get_auth_before_skill_hook(self):
        """do_GET：鉴权必须先于 skill hook（历史缺陷点）。"""
        self._assert_auth_before_hook("do_GET")

    def test_post_auth_before_skill_hook(self):
        self._assert_auth_before_hook("do_POST")

    def test_patch_auth_before_skill_hook(self):
        self._assert_auth_before_hook("do_PATCH")

    def test_delete_auth_before_skill_hook(self):
        self._assert_auth_before_hook("do_DELETE")

    def test_reject_browser_origin_still_checks_bearer(self):
        """鉴权入口必须同时保留 Origin(403) 与 Bearer(401) 两条判断。"""
        body = _method_body(self.source, "_reject_browser_origin")
        self.assertIn("Origin", body, "Origin 拒绝逻辑丢失")
        self.assertIn("403", body, "403 响应丢失")
        self.assertIn("Authorization", body, "Bearer 校验丢失")
        self.assertIn("401", body, "401 响应丢失")

    def test_attachment_route_precedes_auth_by_design(self):
        """附件下载仍应在鉴权之前（window.open 无法带 Bearer，靠签名 token）。"""
        body = _method_body(self.source, "do_GET")
        attach = body.find('"attachments"')
        auth = body.find("_reject_browser_origin")
        self.assertGreater(attach, -1, "附件路由丢失")
        self.assertLess(attach, auth, "附件路由必须早于鉴权（签名 token 设计）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
