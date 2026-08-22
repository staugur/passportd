# -*- coding: utf-8 -*-
"""SITE_BG_IMAGE 全局背景图配置相关测试。

范围：
- 默认配置启用背景图：body 背景图 + 浅化遮罩、导航/页脚/内容区透明
- 启用背景图时去除导航栏边框、阴影与 hover 白色背景框
- SITE_BG_IMAGE 置空时恢复原始实心配色
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

# ---- Mock Redis（必须在导入 passportd 之前） ----
_mock_redis = MagicMock()
_mock_redis.get.return_value = None
_mock_redis.setex.return_value = True
_mock_redis.exists.return_value = False
_mock_redis.delete.return_value = True
_mock_redis.ping.return_value = True
_mock_redis.incr.return_value = 0
_mock_redis.ttl.return_value = 900
_mock_redis.expire.return_value = True

_mock_redis_module = MagicMock()
_mock_redis_module.Redis = MagicMock(return_value=_mock_redis)
_mock_redis_module.Redis.from_url = MagicMock(return_value=_mock_redis)
_mock_redis_module.from_url = MagicMock(return_value=_mock_redis)
sys.modules["redis"] = _mock_redis_module
sys.modules["redis.client"] = MagicMock()

# ---- 导入 passportd ----
from passportd.app import create_app

_BG_URL = "https://hub.saintic.com/openservice/bingpic"


def _css_block(html, selector):
    """提取模板内联 CSS 中指定选择器的规则块文本。"""
    start = html.find(selector)
    if start < 0:
        return ""
    return html[start: html.find("}", start)]


class SiteBgImageTest(unittest.TestCase):
    """SITE_BG_IMAGE 全局背景图测试"""

    @classmethod
    def setUpClass(cls):
        #: 测试环境强制禁用 GeeTest（须在 create_app 之前 patch）
        cls._geetest_patcher = patch(
            "passportd.libs.geetest.geetest_enabled", return_value=False
        )
        cls._geetest_patcher.start()
        app = create_app()
        app.config["TESTING"] = True
        cls.app = app

    @classmethod
    def tearDownClass(cls):
        cls._geetest_patcher.stop()

    def _signin_html(self, bg_url):
        """以指定 SITE_BG_IMAGE 渲染登录页 HTML。"""
        self.app.config["SITE_BG_IMAGE"] = bg_url
        resp = self.app.test_client().get("/user/signin")
        self.assertEqual(resp.status_code, 200)
        return resp.get_data(as_text=True)

    def test_bg_enabled_styles(self):
        """启用背景图时渲染背景图、遮罩，导航/页脚/内容区透明"""
        html = self._signin_html(_BG_URL)
        # body 背景图与浅化遮罩
        self.assertIn('background-image: url("{}")'.format(_BG_URL), html)
        self.assertIn("rgba(255, 255, 255, 0.55)", html)
        # 内容区透明，露出背景图
        self.assertIn("background-color: transparent", _css_block(html, ".page-center"))
        # 导航栏透明
        self.assertIn("background-color: transparent", _css_block(html, ".navbar.is-green"))
        # 页脚透明
        self.assertIn("background-color: transparent", _css_block(html, ".footer.is-light"))

    def test_bg_enabled_removes_lines(self):
        """启用背景图时去除导航栏边框、阴影与 hover 白色背景框"""
        html = self._signin_html(_BG_URL)
        navbar = _css_block(html, ".navbar.is-green")
        # 边框被显式移除（否则透明背景下出现白线）
        self.assertIn("border-bottom: none", navbar)
        navbar_box = _css_block(html, ".navbar {")
        self.assertIn("box-shadow: none", navbar_box)
        hover = _css_block(html, ".navbar.is-green .navbar-item:hover")
        self.assertNotIn("background-color", hover)
        # brand 项（Logo）hover 也强制透明
        brand = _css_block(html, ".navbar.is-green .navbar-brand .navbar-item")
        self.assertIn("background-color: transparent !important", brand)

    def test_bg_disabled_restores(self):
        """SITE_BG_IMAGE 置空时恢复原始实心配色"""
        html = self._signin_html("")
        self.assertNotIn("background-image: url", html)
        self.assertNotIn("rgba(255, 255, 255, 0.55)", html)
        self.assertIn("background-color: #fff", _css_block(html, ".navbar.is-green"))
        self.assertIn("background-color: #f9fafb", _css_block(html, ".footer.is-light"))
        self.assertIn("background-color: #f9fafb", _css_block(html, ".page-center"))


if __name__ == "__main__":
    unittest.main()
