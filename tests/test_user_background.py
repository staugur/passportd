# -*- coding: utf-8 -*-
"""用户自定义背景图（User.background_image）功能测试。

范围：
- update_profile 设置/清除背景图，get_user_background_image 返回正确值
- 非 http/https 背景图 URL 被 ParamError 拒绝
- 登录后页面布局优先使用用户自定义背景图，未设置时回退全局 SITE_BG_IMAGE
- 个人中心资料页展示背景图输入框
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
from passportd.basis.errors import ParamError
from passportd.basis.vars import USER_BG_CACHE_TTL
from passportd.models.model import Auth, User, _ensure_column, db
from passportd.models.user import (
    add_profile,
    generate_jwt,
    get_user_background_image,
    has_account,
    update_profile,
)

_GLOBAL_BG = "https://hub.saintic.com/openservice/bingpic"
_USER_BG = "https://example.com/custom/bg.jpg"

_AUTH = dict(username="testbguser", uid="", token="")


def _css_block(html, selector):
    """提取模板内联 CSS 中指定选择器的规则块文本。"""
    start = html.find(selector)
    if start < 0:
        return ""
    return html[start: html.find("}", start)]


class UserBackgroundImageTest(unittest.TestCase):
    """用户自定义背景图测试"""

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

        with app.app_context():
            if db.is_closed():
                db.connect()
            db.create_tables([User, Auth], safe=True)
            #: 创建测试用户（幂等）
            if not has_account(_AUTH["username"]):
                add_profile(_AUTH["username"], "testpass123")
            auth = Auth.get(Auth.account == _AUTH["username"])
            _AUTH["uid"] = auth.uid
            _AUTH["token"] = generate_jwt(_AUTH["username"])
            #: 清理历史背景图，保证用例互不干扰
            update_profile(_AUTH["uid"], background_image="")

    @classmethod
    def tearDownClass(cls):
        cls._geetest_patcher.stop()
        with cls.app.app_context():
            Auth.delete().where(Auth.account == _AUTH["username"]).execute()
            User.delete().where(User.uid == _AUTH["uid"]).execute()
            db.close()

    def setUp(self):
        self.client = self.app.test_client()
        self.client.set_cookie("sid", _AUTH["token"])
        self.app.config["SITE_BG_IMAGE"] = _GLOBAL_BG

    def tearDown(self):
        with self.app.app_context():
            update_profile(_AUTH["uid"], background_image="")

    # ---------- 模型层 ----------

    def test_get_user_background_image_unset(self):
        """未设置背景图时返回空串"""
        with self.app.app_context():
            self.assertEqual(get_user_background_image(_AUTH["uid"]), "")

    def test_get_user_background_image_set(self):
        """设置背景图后返回对应 URL"""
        with self.app.app_context():
            update_profile(_AUTH["uid"], background_image=_USER_BG)
            self.assertEqual(get_user_background_image(_AUTH["uid"]), _USER_BG)

    def test_update_profile_clear_background(self):
        """空串清除背景图（恢复站点默认）"""
        with self.app.app_context():
            update_profile(_AUTH["uid"], background_image=_USER_BG)
            update_profile(_AUTH["uid"], background_image="")
            self.assertEqual(get_user_background_image(_AUTH["uid"]), "")

    def test_update_profile_invalid_url(self):
        """非 http/https 背景图 URL 被拒绝"""
        for bad in ("javascript:alert(1)", "ftp://example.com/bg.jpg", "/a/b.png", "bg.jpg"):
            with self.subTest(url=bad), self.assertRaises(ParamError):
                update_profile(_AUTH["uid"], background_image=bad)

    def test_update_profile_skip_when_none(self):
        """background_image 不传（None）时保持原值"""
        with self.app.app_context():
            update_profile(_AUTH["uid"], background_image=_USER_BG)
            update_profile(_AUTH["uid"], nickname="newname")
            self.assertEqual(get_user_background_image(_AUTH["uid"]), _USER_BG)

    def test_get_user_background_image_unknown_uid(self):
        """uid 不存在时返回空串"""
        with self.app.app_context():
            self.assertEqual(get_user_background_image("no-such-uid"), "")

    def test_ensure_column_adds_missing_column(self):
        """_ensure_column 能给旧表补充缺失列（回归：曾缺列名致 SQL 报错被静默吞掉）"""
        table = "passport_test_migrate"
        with self.app.app_context():
            try:
                db.execute_sql(
                    'CREATE TABLE IF NOT EXISTS "{}" ("id" INTEGER PRIMARY KEY)'.format(
                        table
                    )
                )
                _ensure_column(
                    table, "bg_probe", "VARCHAR(255) NOT NULL DEFAULT ''"
                )
                cols = {c.name for c in db.get_columns(table)}
                self.assertIn("bg_probe", cols)
            finally:
                db.execute_sql('DROP TABLE IF EXISTS "{}"'.format(table))

    def test_background_image_cache_hit(self):
        """命中 Redis 缓存时不查库"""
        with self.app.app_context():
            with patch("passportd.models.user.rdb.get", return_value=_USER_BG.encode()) as m_get, \
                    patch("passportd.models.user.rdb.setex") as m_setex:
                self.assertEqual(get_user_background_image(_AUTH["uid"]), _USER_BG)
                m_get.assert_called_once()
                m_setex.assert_not_called()

    def test_background_image_cache_miss_backfill(self):
        """未命中缓存时查库并回填 Redis"""
        with self.app.app_context():
            update_profile(_AUTH["uid"], background_image=_USER_BG)
            with patch("passportd.models.user.rdb.get", return_value=None) as m_get, \
                    patch("passportd.models.user.rdb.setex") as m_setex:
                self.assertEqual(get_user_background_image(_AUTH["uid"]), _USER_BG)
                m_get.assert_called_once()
                m_setex.assert_called_once()
                #: 回填使用常量 USER_BG_CACHE_TTL
                self.assertEqual(m_setex.call_args.args[1], USER_BG_CACHE_TTL)

    def test_update_profile_refreshes_bg_cache(self):
        """修改背景图保存成功后，把 Redis 缓存刷新为新值"""
        with self.app.app_context():
            with patch("passportd.models.user.rdb.setex") as m_setex:
                update_profile(_AUTH["uid"], background_image=_USER_BG)
                m_setex.assert_called_once()
                self.assertEqual(m_setex.call_args.args[2], _USER_BG)
                self.assertEqual(m_setex.call_args.args[1], USER_BG_CACHE_TTL)

    def test_update_profile_no_bg_keeps_cache(self):
        """不传 background_image 时不动背景图缓存"""
        with self.app.app_context():
            with patch("passportd.models.user.rdb.setex") as m_setex:
                update_profile(_AUTH["uid"], nickname="new-name")
                m_setex.assert_not_called()

    # ---------- 页面渲染层 ----------

    def test_profile_page_shows_bg_input(self):
        """个人中心资料页展示背景图输入框"""
        resp = self.client.get("/user/profile")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("background_image", html)
        self.assertIn('id="edit-bg-url"', html)

    def test_layout_uses_user_bg_over_global(self):
        """登录后布局优先使用用户自定义背景图"""
        with self.app.app_context():
            update_profile(_AUTH["uid"], background_image=_USER_BG)
        resp = self.client.get("/user/profile")
        html = resp.get_data(as_text=True)
        # 用户背景图生效，全局背景图不出现
        self.assertIn('background-image: url("{}")'.format(_USER_BG), html)
        self.assertNotIn('background-image: url("{}")'.format(_GLOBAL_BG), html)

    def test_layout_fallback_to_global(self):
        """用户未设置背景图时回退全局 SITE_BG_IMAGE"""
        with self.app.app_context():
            update_profile(_AUTH["uid"], background_image="")
        resp = self.client.get("/user/profile")
        html = resp.get_data(as_text=True)
        self.assertIn('background-image: url("{}")'.format(_GLOBAL_BG), html)
        self.assertNotIn('background-image: url("{}")'.format(_USER_BG), html)


if __name__ == "__main__":
    unittest.main()
