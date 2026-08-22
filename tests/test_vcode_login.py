# -*- coding: utf-8 -*-
"""验证码登录即注册相关测试。

范围：
- POST /api/vcode_login 账号不存在时自动注册并登录
- POST /api/send_login_vcode 未注册账号可发送验证码
- POST /user/signup 不再接受邮箱/手机号注册
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
from passportd.models.model import Auth, User, db
from passportd.utils.common import rdb

_ACCOUNT = "vcode_auto_reg@example.com"


class VcodeLoginTest(unittest.TestCase):
    """验证码登录即注册测试"""

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
            # 清理历史测试数据
            auth = Auth.get_or_none(Auth.account == _ACCOUNT)
            if auth:
                User.delete().where(User.uid == auth.uid).execute()
                Auth.delete().where(Auth.account == _ACCOUNT).execute()

    @classmethod
    def tearDownClass(cls):
        cls._geetest_patcher.stop()
        with cls.app.app_context():
            auth = Auth.get_or_none(Auth.account == _ACCOUNT)
            if auth:
                User.delete().where(User.uid == auth.uid).execute()
                Auth.delete().where(Auth.account == _ACCOUNT).execute()

    def _post_vcode_login(self, account, code="123456"):
        with patch.object(rdb, "get", return_value=code):
            return self.app.test_client().post(
                "/api/vcode_login",
                data={"account": account, "code": code},
            )

    def test_vcode_login_auto_register(self):
        """账号不存在时验证码登录自动注册并登录"""
        resp = self._post_vcode_login(_ACCOUNT)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"], data)

        with self.app.app_context():
            auth = Auth.get_or_none(Auth.account == _ACCOUNT)
            self.assertIsNotNone(auth, "验证码登录应自动创建 Auth 记录")
            user = User.get_or_none(User.uid == auth.uid)
            self.assertIsNotNone(user, "自动注册应创建 User 记录")
            self.assertIsNone(user.password_hash, "自动注册账号不应有密码")

    def test_send_login_vcode_allows_unregistered(self):
        """未注册账号也可发送登录验证码（验证码登录即注册）"""
        with patch(
            "passportd.libs.interface.VCodeInterface.send_email",
            return_value={"success": True, "message": "sent"},
        ):
            resp = self.app.test_client().post(
                "/api/send_login_vcode",
                data={"account": _ACCOUNT},
            )
        data = resp.get_json()
        self.assertTrue(data["success"], data)

    def test_signup_rejects_email(self):
        """注册页不再接受邮箱/手机号注册"""
        resp = self.app.test_client().post(
            "/user/signup",
            data={
                "account": _ACCOUNT,
                "password": "testpass123",
                "repassword": "testpass123",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("注册仅支持用户名", resp.get_data(as_text=True))
