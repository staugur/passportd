# -*- coding: utf-8 -*-
"""Telegram Login Widget 模块单元测试。

范围：
- 回执签名校验（_verify_telegram_login）
- auth_date 新鲜度校验（_check_auth_date）
- 用户信息构造（_build_telegram_userinfo）
"""

import hmac
import unittest
import unittest.mock as mock
from hashlib import sha256
from time import time

from passportd.basis.conf import config

#: 测试用 Bot Token（模拟 @BotFather 发放的格式）
_BOT_TOKEN = "123456789:TEST-BOT-TOKEN"

# 预先注入测试 Token，确保 telegram 插件模块首次导入时 __state__ = enabled，
# 蓝图与 /oauth2/telegram/authorized 路由得以注册（供路由级测试使用）。
config["TELEGRAM_BOT_TOKEN"] = _BOT_TOKEN


def _make_tg_data(**overrides):
    """构造合法的 Telegram 回执数据（含正确 hash 签名）。"""
    data = {
        "id": "123456789",
        "first_name": "Alice",
        "last_name": "测试",
        "username": "alice_tg",
        "photo_url": "https://cdn.example.com/a.jpg",
        "auth_date": str(int(time())),
    }
    secret = sha256(_BOT_TOKEN.encode("utf-8")).digest()
    items = sorted(data.items())
    data_check_string = "\n".join(f"{k}={v}" for k, v in items)
    data["hash"] = hmac.new(
        secret, data_check_string.encode("utf-8"), sha256
    ).hexdigest()
    data.update(overrides)
    return data


class TestTelegramVerifySignature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from passportd import app as passportd_app

        passportd_app.create_app()
        from passportd.modules.oauth2_telegram import _verify_telegram_login

        cls._verify = staticmethod(_verify_telegram_login)

    def test_valid_signature(self):
        self.assertTrue(self._verify(_make_tg_data(), _BOT_TOKEN))

    def test_wrong_token(self):
        self.assertFalse(self._verify(_make_tg_data(), "wrong-token"))

    def test_tampered_field(self):
        data = _make_tg_data()
        data["first_name"] = "Eve"
        self.assertFalse(self._verify(data, _BOT_TOKEN))

    def test_missing_hash(self):
        data = _make_tg_data()
        del data["hash"]
        self.assertFalse(self._verify(data, _BOT_TOKEN))


class TestTelegramAuthDate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from passportd import app as passportd_app

        passportd_app.create_app()
        from passportd.modules.oauth2_telegram import _check_auth_date

        cls._check = staticmethod(_check_auth_date)

    def test_fresh(self):
        self.assertTrue(self._check(int(time()), 86400))

    def test_expired(self):
        self.assertFalse(self._check(int(time()) - 90000, 86400))

    def test_invalid_value(self):
        self.assertFalse(self._check("not-a-number", 86400))


class TestTelegramBuildUserinfo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from passportd import app as passportd_app

        passportd_app.create_app()
        from passportd.modules.oauth2_telegram import _build_telegram_userinfo

        cls._build = staticmethod(_build_telegram_userinfo)

    def test_account_and_tpid(self):
        info = self._build(_make_tg_data())
        self.assertEqual(info["account"], "telegram.123456789")
        self.assertEqual(info["tpid"], "123456789")

    def test_profile_fields(self):
        info = self._build(_make_tg_data())
        self.assertEqual(info["name"], "Alice 测试")
        self.assertEqual(info["picture"], "https://cdn.example.com/a.jpg")

    def test_no_photo(self):
        data = _make_tg_data()
        data["photo_url"] = ""
        info = self._build(data)
        self.assertEqual(info["picture"], "")


class TestTelegramAuthorized(unittest.TestCase):
    """authorized 路由：GET/POST 双兼容、验签与错误路径。"""

    @classmethod
    def setUpClass(cls):
        from passportd import app as passportd_app

        cls.app = passportd_app.create_app()
        cls._make_data = staticmethod(_make_tg_data)

    @mock.patch("passportd.libs.interface.OAuthClient.oauth2_authorized_handler")
    def test_get_request_accepts_query(self, mock_handler):
        """GET 携带 query 参数可直接完成验签（不再 405）"""
        mock_handler.return_value = ("ok", 200)
        data = self._make_data()
        with mock.patch.dict(
            "passportd.modules.oauth2_telegram.config",
            {"TELEGRAM_BOT_TOKEN": _BOT_TOKEN},
        ):
            resp = self.app.test_client().get(
                "/oauth2/telegram/authorized", query_string=data
            )
        self.assertEqual(resp.status_code, 200)
        mock_handler.assert_called_once()

    @mock.patch("passportd.libs.interface.OAuthClient.oauth2_authorized_handler")
    def test_post_request_accepts_form(self, mock_handler):
        """POST form 提交（widget 默认方式）仍可用"""
        mock_handler.return_value = ("ok", 200)
        data = self._make_data()
        with mock.patch.dict(
            "passportd.modules.oauth2_telegram.config",
            {"TELEGRAM_BOT_TOKEN": _BOT_TOKEN},
        ):
            resp = self.app.test_client().post(
                "/oauth2/telegram/authorized", data=data
            )
        self.assertEqual(resp.status_code, 200)
        mock_handler.assert_called_once()

    def test_invalid_signature(self):
        """签名错误返回 403"""
        data = self._make_data()
        data["first_name"] = "Eve"
        with mock.patch.dict(
            "passportd.modules.oauth2_telegram.config",
            {"TELEGRAM_BOT_TOKEN": _BOT_TOKEN},
        ):
            resp = self.app.test_client().get(
                "/oauth2/telegram/authorized", query_string=data
            )
        self.assertEqual(resp.status_code, 403)

    def test_missing_fields(self):
        """缺少 id/hash 返回 400"""
        with mock.patch.dict(
            "passportd.modules.oauth2_telegram.config",
            {"TELEGRAM_BOT_TOKEN": _BOT_TOKEN},
        ):
            resp = self.app.test_client().get(
                "/oauth2/telegram/authorized", query_string={"id": "1"}
            )
        self.assertEqual(resp.status_code, 400)


class TestTelegramBotUsername(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from passportd import app as passportd_app

        passportd_app.create_app()
        from passportd.modules.oauth2_telegram import (
            _build_proxies,
            _fetch_bot_username,
            _get_bot_username,
        )

        cls._proxies = staticmethod(_build_proxies)
        cls._fetch = staticmethod(_fetch_bot_username)
        cls._get = staticmethod(_get_bot_username)

    @mock.patch("passportd.modules.oauth2_telegram.rdb")
    def test_get_from_config(self, mock_rdb):
        mock_rdb.get.return_value = None
        with mock.patch.dict(
            "passportd.modules.oauth2_telegram.config",
            {"TELEGRAM_BOT_TOKEN": _BOT_TOKEN, "TELEGRAM_BOT_USERNAME": "passportd_bot"},
        ):
            self.assertEqual(self._get(), "passportd_bot")
        mock_rdb.setex.assert_not_called()

    @mock.patch("passportd.modules.oauth2_telegram.rdb")
    def test_get_from_cache(self, mock_rdb):
        mock_rdb.get.return_value = "cached_bot"
        self.assertEqual(self._get(), "cached_bot")

    @mock.patch("passportd.modules.oauth2_telegram.rdb")
    @mock.patch("passportd.modules.oauth2_telegram._fetch_bot_username")
    def test_get_via_api_and_cache(self, mock_fetch, mock_rdb):
        mock_rdb.get.return_value = None
        mock_fetch.return_value = "passportd_bot"
        with mock.patch.dict(
            "passportd.modules.oauth2_telegram.config",
            {"TELEGRAM_BOT_TOKEN": _BOT_TOKEN, "TELEGRAM_BOT_USERNAME": ""},
        ):
            self.assertEqual(self._get(), "passportd_bot")
        mock_fetch.assert_called_once()
        mock_rdb.setex.assert_called_once()

    @mock.patch("passportd.modules.oauth2_telegram.rdb")
    @mock.patch("passportd.modules.oauth2_telegram._fetch_bot_username")
    def test_get_api_fail_no_cache(self, mock_fetch, mock_rdb):
        mock_rdb.get.return_value = None
        mock_fetch.return_value = ""
        with mock.patch.dict(
            "passportd.modules.oauth2_telegram.config",
            {"TELEGRAM_BOT_TOKEN": _BOT_TOKEN, "TELEGRAM_BOT_USERNAME": ""},
        ):
            self.assertEqual(self._get(), "")
        mock_rdb.setex.assert_not_called()

    @mock.patch("passportd.modules.oauth2_telegram.requests.get")
    def test_fetch_success(self, mock_get):
        mock_get.return_value = mock.Mock(
            raise_for_status=mock.Mock(),
            json=lambda: {"ok": True, "result": {"username": "passportd_bot"}},
        )
        self.assertEqual(self._fetch(_BOT_TOKEN), "passportd_bot")
        mock_get.assert_called_once()
        self.assertIn("getMe", mock_get.call_args.args[0])

    @mock.patch("passportd.modules.oauth2_telegram.requests.get")
    def test_fetch_failure(self, mock_get):
        mock_get.side_effect = Exception("network down")
        self.assertEqual(self._fetch(_BOT_TOKEN), "")

    def test_proxies_config(self):
        with mock.patch.dict(
            "passportd.modules.oauth2_telegram.config",
            {"TELEGRAM_API_PROXY": "http://127.0.0.1:7890"},
        ):
            self.assertEqual(
                self._proxies(),
                {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
            )
        with mock.patch.dict(
            "passportd.modules.oauth2_telegram.config",
            {"TELEGRAM_API_PROXY": ""},
        ):
            self.assertIsNone(self._proxies())

    def test_proxies_fallback_to_global(self):
        """专属代理为空时回退全局 PROXY"""
        with mock.patch.dict(
            "passportd.modules.oauth2_telegram.config",
            {
                "TELEGRAM_API_PROXY": "",
                "PROXY": "http://127.0.0.1:1080",
            },
        ):
            self.assertEqual(
                self._proxies(),
                {"http": "http://127.0.0.1:1080", "https": "http://127.0.0.1:1080"},
            )

    def test_proxies_specific_precedence(self):
        """专属代理优先于全局 PROXY"""
        with mock.patch.dict(
            "passportd.modules.oauth2_telegram.config",
            {
                "TELEGRAM_API_PROXY": "http://127.0.0.1:7890",
                "PROXY": "http://127.0.0.1:1080",
            },
        ):
            self.assertEqual(
                self._proxies(),
                {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
            )


if __name__ == "__main__":
    unittest.main()
