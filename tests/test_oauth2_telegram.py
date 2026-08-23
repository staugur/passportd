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

#: 测试用 Bot Token（模拟 @BotFather 发放的格式）
_BOT_TOKEN = "123456789:TEST-BOT-TOKEN"


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


if __name__ == "__main__":
    unittest.main()
