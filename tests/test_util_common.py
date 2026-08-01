# -*- coding: utf-8 -*-

import unittest

from passportd.utils.common import (
    parse_db_uri,
    is_local_account,
    is_third_account,
    parse_account_classify,
    email_check,
    phone_check,
    username_check,
    multi_phone_check,
    appname_check,
    is_valid_user_role,
    gen_uid,
    jwt_encode,
    jwt_decode,
    jwt_decode_payload_without_verify,
    is_valid_http_url,
    is_valid_ipv4,
    generate_verification_code,
    generate_digital_verification_code,
)
from passportd.basis.errors import JWTError, ParamError


class UtilsTest(unittest.TestCase):
    # ==================== parse_db_uri ====================

    def test_db_uri(self):
        uris = [
            dict(
                uri="sqlite:///tmp/foo.db",
                opt=dict(provider="sqlite", filename="/tmp/foo.db"),
            ),
            dict(
                uri="file:///tmp/foo.dat",
                opt=dict(provider="file", filename="/tmp/foo.dat"),
            ),
            dict(
                uri="mysql://A:B@localhost/test",
                opt=dict(provider="mysql", user="A", password="B", database="test"),
            ),
            dict(
                uri="mongo://127.0.0.1:27017/admin",
                opt=dict(provider="mongo", database="admin", host="127.0.0.1:27017"),
            ),
            dict(
                uri="redis://:123@localhost/1",
                opt=dict(provider="redis", database="1", host="localhost"),
            ),
            dict(
                uri="postgresql://A:B@localhost/test",
                opt=dict(
                    provider="postgresql",
                    user="A",
                    password="B",
                    database="test",
                ),
            ),
            dict(
                uri="oracle://A:B@127.0.0.1:1521/sidname",
                opt=dict(
                    provider="oracle",
                    user="A",
                    password="B",
                    host="127.0.0.1:1521",
                    database="sidname",
                ),
            ),
        ]
        for i in uris:
            opt = parse_db_uri(i["uri"])
            for k, v in i["opt"].items():
                self.assertEqual(opt[k], v)

    def test_db_uri_empty(self):
        self.assertEqual(parse_db_uri(""), {})
        self.assertEqual(parse_db_uri(None), {})

    def test_db_uri_sqlite_create_db(self):
        opt = parse_db_uri("sqlite:///tmp/test.db")
        self.assertTrue(opt.get("create_db"))

    # ==================== 账号校验 ====================

    def test_account_local(self):
        """本地账号校验"""
        # 用户名太短
        self.assertFalse(is_local_account("abc"))
        self.assertTrue(is_local_account("abcd"))
        # 邮箱格式
        self.assertFalse(is_local_account("a@qq."))
        self.assertTrue(is_local_account("a@qq.com"))
        # 手机号格式
        self.assertFalse(is_local_account("23812345678"))
        self.assertTrue(is_local_account("13812345678"))
        # 空值和类型
        self.assertFalse(is_local_account(""))
        self.assertFalse(is_local_account(None))

    def test_account_third(self):
        """第三方账号校验"""
        self.assertFalse(is_third_account("github-openid"))
        self.assertFalse(is_third_account("1.github-openid"))
        self.assertTrue(is_third_account("github.github-openid"))
        self.assertTrue(is_third_account("qq.qq-openid"))
        self.assertTrue(is_third_account("weibo.weibo-uid123"))
        self.assertTrue(is_third_account("gitee.332813"))
        # provider 必须以字母开头
        self.assertFalse(is_third_account("2git.provider"))
        # oauth_name 至少3位
        self.assertFalse(is_third_account("github.ab"))
        # 空值和类型
        self.assertFalse(is_third_account(""))
        self.assertFalse(is_third_account(None))

    def test_parse_account_classify(self):
        """账号类型解析"""
        self.assertIsNone(parse_account_classify("abc"))
        self.assertEqual(parse_account_classify("abcde"), "username")
        self.assertEqual(parse_account_classify("a@qq.com"), "email")
        self.assertEqual(parse_account_classify("13812345678"), "mobile")
        self.assertEqual(parse_account_classify("weibo.weibo-uid123"), "3rd")
        self.assertEqual(parse_account_classify("gitee.332813"), "3rd")
        self.assertEqual(parse_account_classify("github.github-openid"), "3rd")
        self.assertIsNone(parse_account_classify("1.other"))
        self.assertIsNone(parse_account_classify(""))
        self.assertIsNone(parse_account_classify(None))

    # ==================== 格式校验 ====================

    def test_email_check(self):
        self.assertTrue(email_check("test@example.com"))
        self.assertTrue(email_check("a@b.cd"))
        self.assertTrue(email_check("user+tag@domain.co.uk"))
        self.assertFalse(email_check(""))
        self.assertFalse(email_check("notanemail"))
        self.assertFalse(email_check("@missinguser.com"))
        self.assertFalse(email_check(None))

    def test_phone_check(self):
        self.assertTrue(phone_check("13812345678"))
        self.assertTrue(phone_check("15900001111"))
        self.assertTrue(phone_check("18888888888"))
        self.assertFalse(phone_check("12345678901"))  # 2开头
        self.assertFalse(phone_check("1381234567"))  # 10位
        self.assertFalse(phone_check("138123456789"))  # 12位
        self.assertFalse(phone_check(""))
        self.assertFalse(phone_check(None))

    def test_username_check(self):
        self.assertTrue(username_check("abcd"))
        self.assertTrue(username_check("test_user"))
        self.assertTrue(username_check("a1234567890123456789012345678901"))  # 32位
        self.assertFalse(username_check("abc"))  # 太短
        self.assertFalse(username_check("123abc"))  # 数字开头
        self.assertFalse(username_check("Abcd"))  # 大写开头
        self.assertFalse(username_check("a" + "b" * 32))  # 超过32位
        self.assertFalse(username_check(""))
        self.assertFalse(username_check(None))

    def test_multi_phone_check(self):
        self.assertTrue(multi_phone_check("13812345678"))
        self.assertTrue(multi_phone_check("13812345678,15900001111"))
        self.assertTrue(multi_phone_check("13812345678,15900001111,18888888888"))
        self.assertFalse(multi_phone_check("13812345678,invalid"))
        self.assertFalse(multi_phone_check(""))
        self.assertFalse(multi_phone_check(None))

    def test_appname_check(self):
        self.assertTrue(appname_check("test_app"))
        self.assertTrue(appname_check("my-app-name"))
        self.assertTrue(appname_check("a1234567890123456789012345678901"))  # 32位
        self.assertFalse(appname_check("abc"))  # 太短
        self.assertFalse(appname_check("123abc"))  # 数字开头
        self.assertFalse(appname_check("AppName"))  # 大写
        self.assertFalse(appname_check(""))
        self.assertFalse(appname_check(None))

    def test_is_valid_user_role(self):
        self.assertTrue(is_valid_user_role("SuperAdmin"))
        self.assertTrue(is_valid_user_role("Admin"))
        self.assertTrue(is_valid_user_role("User"))
        self.assertTrue(is_valid_user_role("custom:role"))
        self.assertTrue(is_valid_user_role("a:b"))
        self.assertFalse(is_valid_user_role("invalid"))
        self.assertFalse(is_valid_user_role(""))
        self.assertFalse(is_valid_user_role("too:many:parts"))

    # ==================== JWT ====================

    def test_jwt(self):
        sk = "test-secret-key-long-enough"
        data = dict(a=1, b="2", c=None, d=[])
        # test basic
        tk = jwt_encode(sk, data)
        rt = jwt_decode(tk, sk)
        with self.assertRaises(TypeError):
            jwt_decode(tk)
        self.assertEqual(tk.count("."), 2)
        self.assertIn("iss", rt)
        self.assertIn("a", rt)
        self.assertEqual(rt["a"], 1)
        # test sub
        sub = "test"
        tk2 = jwt_encode(sk, dict(sub=sub))
        self.assertEqual(jwt_decode(tk2, sk)["sub"], sub)
        with self.assertRaises(JWTError):
            jwt_decode(tk2, sk, sub="xyz")

    def test_jwt_encode_with_expire(self):
        sk = "test-secret-key-long-enough"
        # 合法 expire
        tk = jwt_encode(sk, dict(sub="user1"), expire=600)
        self.assertIsNotNone(tk)
        # 太短的 expire
        with self.assertRaises(ParamError):
            jwt_encode(sk, dict(sub="user1"), expire=200)
        # 无 payload 时也能正常编码
        tk2 = jwt_encode(sk, expire=3600)
        rt = jwt_decode(tk2, sk)
        self.assertIn("iss", rt)

    def test_jwt_decode_payload_without_verify(self):
        sk = "test-secret-key-long-enough"
        tk = jwt_encode(sk, dict(sub="user1", custom="value"), expire=600)
        payload = jwt_decode_payload_without_verify(tk)
        self.assertEqual(payload["sub"], "user1")
        self.assertEqual(payload["custom"], "value")
        self.assertIn("iss", payload)

    def test_jwt_decode_payload_without_verify_invalid(self):
        with self.assertRaises(ValueError):
            jwt_decode_payload_without_verify("")
        with self.assertRaises(ValueError):
            jwt_decode_payload_without_verify("not.valid")
        with self.assertRaises(ValueError):
            jwt_decode_payload_without_verify("only.twoparts")

    # ==================== URL / IP 校验 ====================

    def test_is_valid_http_url(self):
        # 合法链接
        self.assertTrue(is_valid_http_url("http://example.com"))
        self.assertTrue(
            is_valid_http_url("https://sub.example.com:8080/path?query=param#hash")
        )
        self.assertTrue(is_valid_http_url("http://localhost"))
        self.assertTrue(is_valid_http_url("http://192.168.1.1"))
        # 非法链接
        self.assertFalse(is_valid_http_url("ftp://example.com"))
        self.assertFalse(is_valid_http_url("http://-example.com"))
        self.assertFalse(is_valid_http_url("http://example..com"))
        self.assertFalse(is_valid_http_url("http://example.com:80abc"))
        self.assertFalse(is_valid_http_url("http://example.com/path with space"))

    def test_is_valid_ipv4(self):
        # 合法 IPv4
        self.assertTrue(is_valid_ipv4("192.168.1.1"))
        self.assertTrue(is_valid_ipv4("0.0.0.0"))
        self.assertTrue(is_valid_ipv4("255.255.255.255"))
        self.assertTrue(is_valid_ipv4("001.202.033.244"))  # 允许前导零
        # 非法 IPv4
        self.assertFalse(is_valid_ipv4("256.1.1.1"))  # 数字超限
        self.assertFalse(is_valid_ipv4("192.168.1"))  # 不足4段
        self.assertFalse(is_valid_ipv4("192.168.1.1.1"))  # 超过4段
        self.assertFalse(is_valid_ipv4("192.168.1."))  # 结尾多小数点
        self.assertFalse(is_valid_ipv4("192.168.1.a"))  # 非数字字符
        self.assertFalse(is_valid_ipv4(""))

    # ==================== 验证码 / UID 生成 ====================

    def test_gen_uid(self):
        uid = gen_uid()
        self.assertIsInstance(uid, str)
        self.assertEqual(len(uid), 22)
        self.assertTrue(uid.islower())
        # 两次生成的值应不同
        self.assertNotEqual(gen_uid(), gen_uid())

    def test_generate_verification_code(self):
        code = generate_verification_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isalnum())
        # 自定义长度
        code8 = generate_verification_code(8)
        self.assertEqual(len(code8), 8)
        # 两次生成值应不同（概率极高）
        codes = set(generate_verification_code() for _ in range(10))
        self.assertGreater(len(codes), 1)

    def test_generate_digital_verification_code(self):
        code = generate_digital_verification_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        # 自定义长度
        code4 = generate_digital_verification_code(4)
        self.assertEqual(len(code4), 4)
        self.assertTrue(code4.isdigit())


if __name__ == "__main__":
    unittest.main()
