"""Flask API 接口测试。

测试范围（api.py）：
- GET  /api/key                公钥
- POST /api/user/signup        注册
- POST /api/user/change_password 修改密码
- GET  /api/user/login_history 登录记录
- POST /api/upload             上传

跳过：OIDC 客户端管理、验证码发送/登录相关接口。
"""

import json
import os
import shutil
import sys
import unittest
from unittest.mock import MagicMock

# ---- Mock Redis（必须在导入 passportd 之前） ----
_mock_redis = MagicMock()
_mock_redis.get.return_value = None
_mock_redis.setex.return_value = True
_mock_redis.exists.return_value = False
_mock_redis.delete.return_value = True
_mock_redis.ping.return_value = True

_mock_redis_module = MagicMock()
_mock_redis_module.Redis = MagicMock(return_value=_mock_redis)
_mock_redis_module.Redis.from_url = MagicMock(return_value=_mock_redis)
_mock_redis_module.from_url = MagicMock(return_value=_mock_redis)
sys.modules["redis"] = _mock_redis_module
sys.modules["redis.client"] = MagicMock()

# ---- 导入 passportd ----
from passportd.app import create_app
from passportd.models.user import add_profile, generate_jwt
from passportd.models.model import db, User, Auth, LoginRecord


_AUTH = dict(username="testapiuser", uid="", token="")

# 1x1 红色像素 PNG（base64）
_VALID_PNG_DATA_URI = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAE"
    "AAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)


class ApiTest(unittest.TestCase):
    """API 接口测试"""

    @classmethod
    def setUpClass(cls):
        app = create_app()
        app.config["TESTING"] = True
        cls.app = app

        with app.app_context():
            if db.is_closed():
                db.connect()
            db.create_tables([User, Auth, LoginRecord], safe=True)

            # 创建测试用户
            add_profile(_AUTH["username"], "testpass123")
            auth = Auth.get(Auth.account == _AUTH["username"])
            _AUTH["uid"] = auth.uid
            _AUTH["token"] = generate_jwt(_AUTH["username"])

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            # 删除测试用户及其 Auth 记录
            Auth.delete().where(Auth.account == _AUTH["username"]).execute()
            User.delete().where(User.uid == _AUTH["uid"]).execute()
            # 删除测试中可能创建的残留账号
            Auth.delete().where(
                Auth.account.in_(
                    ["testapinew", "testapidup", "testapimismatch"]
                )
            ).execute()
            # 清理上传目录
            upload_dir = cls.app.config["LOCAL_UPLOAD_FOLDER"]
            if os.path.isdir(upload_dir):
                shutil.rmtree(upload_dir, ignore_errors=True)
            db.close()

    def setUp(self):
        """每个测试方法前创建新 client，避免 cookie 污染"""
        self.client = self.app.test_client()

    def _login(self):
        """设置登录 cookie"""
        self.client.set_cookie("sid", _AUTH["token"])

    # ---------- GET /api/key ----------

    def test_key_returns_public_key(self):
        """获取 RSA 公钥成功"""
        resp = self.client.get("/api/key")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertIn("key", data.get("data", {}))

    # ---------- POST /api/user/signup ----------

    def test_signup_success(self):
        """用户名注册成功"""
        resp = self.client.post(
            "/api/user/signup",
            data=dict(
                account="testapinew",
                password="newpass123",
                repassword="newpass123",
            ),
        )
        data = json.loads(resp.data)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(data.get("success"))

    def test_signup_missing_fields(self):
        """缺少必填字段时返回失败"""
        resp = self.client.post(
            "/api/user/signup", data=dict(account="", password="")
        )
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    def test_signup_password_mismatch(self):
        """两次密码不一致"""
        resp = self.client.post(
            "/api/user/signup",
            data=dict(
                account="testapimismatch",
                password="pass1",
                repassword="pass2",
            ),
        )
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    def test_signup_duplicate_account(self):
        """重复账号注册失败"""
        resp = self.client.post(
            "/api/user/signup",
            data=dict(
                account=_AUTH["username"],
                password="pass123456",
                repassword="pass123456",
            ),
        )
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    # ---------- POST /api/user/change_password ----------

    def test_change_password_success(self):
        """已登录，修改密码成功"""
        self._login()
        resp = self.client.post(
            "/api/user/change_password",
            data=dict(new_password="newtest456", repassword="newtest456"),
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))

    def test_change_password_not_match(self):
        """新密码与确认密码不一致"""
        self._login()
        resp = self.client.post(
            "/api/user/change_password",
            data=dict(new_password="newtest456", repassword="notmatch"),
        )
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    def test_change_password_no_login(self):
        """未登录时修改密码失败"""
        resp = self.client.post(
            "/api/user/change_password",
            data=dict(new_password="pass", repassword="pass"),
        )
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    def test_change_password_too_short(self):
        """新密码长度不足"""
        self._login()
        resp = self.client.post(
            "/api/user/change_password",
            data=dict(new_password="12", repassword="12"),
        )
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    def test_change_password_missing_new(self):
        """缺少新密码"""
        self._login()
        resp = self.client.post(
            "/api/user/change_password",
            data=dict(new_password="", repassword=""),
        )
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    # ---------- GET /api/user/login_history ----------

    def test_login_history_with_auth(self):
        """已登录，获取登录记录"""
        self._login()
        resp = self.client.get("/api/user/login_history")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertIsInstance(
            data.get("data", {}).get("login_history"), list
        )

    def test_login_history_no_login(self):
        """未登录，获取登录记录失败"""
        resp = self.client.get("/api/user/login_history")
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    # ---------- POST /api/upload ----------

    def test_upload_no_login(self):
        """未登录时上传失败"""
        resp = self.client.post(
            "/api/upload", data=dict(base64=_VALID_PNG_DATA_URI)
        )
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    def test_upload_empty_data(self):
        """上传但未提供 base64 数据"""
        self._login()
        resp = self.client.post("/api/upload", data={})
        self.assertEqual(resp.status_code, 400)

    def test_upload_success(self):
        """已登录，上传 base64 图片成功"""
        self._login()
        resp = self.client.post(
            "/api/upload", data=dict(base64=_VALID_PNG_DATA_URI)
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertIn("url", data.get("data", {}))


if __name__ == "__main__":
    unittest.main()
