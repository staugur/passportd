# -*- coding: utf-8 -*-
"""Apple Sign in with Apple OAuth2 模块单元测试。

范围：
- parse_userinfo 回调（account/tpid 格式、email 透传）
- id_token（JWT）payload 解析
- client_secret（ES256 JWT）动态生成与 claims 校验
"""

import base64
import json
import unittest

from joserfc.jwk import ECKey

from passportd.basis.conf import config


def _make_jwt(claims: dict) -> str:
    """手工构造一个不验签的 JWT，用于模拟 Apple 返回的 id_token。"""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.signature"


def _decode_jwt_part(token: str, part: int) -> dict:
    """base64url 解码 JWT 的 header(0)/payload(1) 段。"""
    seg = token.split(".")[part]
    seg += "=" * (-len(seg) % 4)
    return json.loads(base64.urlsafe_b64decode(seg))


class TestAppleParseUserinfo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from passportd import app as passportd_app

        passportd_app.create_app()
        from passportd.modules.oauth2_apple import _parse_apple_userinfo

        cls._parse = staticmethod(_parse_apple_userinfo)

    def test_account_and_tpid(self):
        info = self._parse(sub="000123.1a2b3c")
        self.assertEqual(info["account"], "apple.000123.1a2b3c")
        self.assertEqual(info["tpid"], "000123.1a2b3c")
        self.assertEqual(info["name"], "")

    def test_email_private_relay(self):
        info = self._parse(sub="0001", email="user@privaterelay.appleid.com")
        self.assertEqual(info["email"], "user@privaterelay.appleid.com")

    def test_missing_email(self):
        info = self._parse(sub="0001")
        self.assertEqual(info["email"], "")

    def test_extra_claims_ignored(self):
        info = self._parse(sub="0001", aud="https://appleid.apple.com", exp=9999999999)
        self.assertEqual(info["account"], "apple.0001")


class TestAppleParseIdToken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from passportd import app as passportd_app

        passportd_app.create_app()
        from passportd.modules.oauth2_apple import _apple_parse_id_token

        cls._parse = staticmethod(_apple_parse_id_token)

    def test_parse_claims(self):
        claims = {"sub": "000123.1a2b3c", "email": "a@b.com", "email_verified": True}
        result = self._parse(_make_jwt(claims))
        self.assertEqual(result["sub"], "000123.1a2b3c")
        self.assertEqual(result["email"], "a@b.com")
        self.assertEqual(result["email_verified"], True)


class TestAppleClientSecret(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from passportd import app as passportd_app

        passportd_app.create_app()
        from passportd.modules.oauth2_apple import _apple_client_secret

        cls._secret = staticmethod(_apple_client_secret)

    def test_generated_secret_claims(self):
        key = ECKey.generate_key(crv="P-256")
        config["APPLE_TEAM_ID"] = "TESTTEAM"
        config["APPLE_KEY_ID"] = "TESTKEYID"
        config["APPLE_CLIENT_ID"] = "com.example.passport"
        config["APPLE_PRIVATE_KEY"] = key.as_pem(private=True).decode()

        token = self._secret()
        header = _decode_jwt_part(token, 0)
        claims = _decode_jwt_part(token, 1)

        self.assertEqual(header["alg"], "ES256")
        self.assertEqual(header["kid"], "TESTKEYID")
        self.assertEqual(claims["iss"], "TESTTEAM")
        self.assertEqual(claims["sub"], "com.example.passport")
        self.assertEqual(claims["aud"], "https://appleid.apple.com")
        self.assertLess(claims["exp"] - claims["iat"], 180 * 24 * 3600 + 10)


if __name__ == "__main__":
    unittest.main()
