# -*- coding: utf-8 -*-
"""小米开放平台 OAuth2 模块单元测试。

范围：
- parse_userinfo 回调（account/tpid 格式、昵称头像透传）
"""

import unittest


class TestXiaomiParseUserinfo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from passportd import app as passportd_app

        passportd_app.create_app()
        from passportd.modules.oauth2_xiaomi import _parse_xiaomi_userinfo

        cls._parse = staticmethod(_parse_xiaomi_userinfo)

    def test_account_and_tpid(self):
        info = self._parse(userId="123456789")
        self.assertEqual(info["account"], "xiaomi.123456789")
        self.assertEqual(info["tpid"], "123456789")

    def test_profile_fields(self):
        info = self._parse(
            userId="123",
            miliaoNick="小明",
            avatarUrl="https://cdn.example.com/a.jpg",
        )
        self.assertEqual(info["name"], "小明")
        self.assertEqual(info["picture"], "https://cdn.example.com/a.jpg")

    def test_missing_profile(self):
        info = self._parse(userId="123")
        self.assertEqual(info["name"], "")
        self.assertEqual(info["picture"], "")


if __name__ == "__main__":
    unittest.main()
