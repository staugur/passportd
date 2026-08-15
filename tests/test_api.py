"""Flask API 接口测试。

测试范围（api.py）：
- GET  /api/key                公钥
- POST /api/user/change_password 修改密码
- GET  /api/user/login_history 登录记录
- POST /api/upload             上传
- 页面路由 /user/signup、/user/signin 的加密密码传输（front.py）

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
from passportd.basis.common import now
from passportd.models.model import Auth, LoginRecord, User, db
from passportd.models.user import add_profile, generate_jwt, has_account
from passportd.utils.common import rsa_encrypt

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

            # 创建测试用户（幂等，避免测试类执行顺序导致重复创建）
            if not has_account(_AUTH["username"]):
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
                    [
                        "testfrontnew",
                        "testfrontlogin",
                    ]
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

    # ---------- 页面路由：/user/signup、/user/signin（加密密码传输） ----------

    def test_front_signup_with_encrypted_password(self):
        """注册页面支持 RSA 加密密码（JWE）提交"""
        resp = self.client.post(
            "/user/signup",
            data=dict(
                account="testfrontnew",
                encrypted_password=rsa_encrypt("newpass123"),
                encrypted_repassword=rsa_encrypt("newpass123"),
            ),
            follow_redirects=True,
        )
        # 注册成功应 302 到登录页并带成功提示
        self.assertEqual(resp.status_code, 200)
        self.assertIn("注册成功", resp.get_data(as_text=True))

    def test_front_signin_with_encrypted_password(self):
        """密码登录支持 RSA 加密密码（JWE）提交"""
        # 注册独立账号，避免受其他测试（改密码）影响
        self.client.post(
            "/user/signup",
            data=dict(
                account="testfrontlogin",
                encrypted_password=rsa_encrypt("newpass123"),
                encrypted_repassword=rsa_encrypt("newpass123"),
            ),
        )
        resp = self.client.post(
            "/user/signin",
            data=dict(
                account="testfrontlogin",
                encrypted_password=rsa_encrypt("newpass123"),
            ),
        )
        # 登录成功应 302 跳转并设置登录态 Cookie
        self.assertEqual(resp.status_code, 302)
        self.assertIn("sid", resp.headers.get("Set-Cookie", ""))
        # 携带 Cookie 访问个人主页验证已登录
        resp2 = self.client.get("/", follow_redirects=True)
        self.assertIn("个人主页", resp2.get_data(as_text=True))

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

    def test_change_password_same_as_current(self):
        """新密码与当前密码相同时返回 PASSWORD_SAME_AS_OLD"""
        self._login()
        # 先设置一个固定密码，再以相同密码修改，避免依赖用例执行顺序
        self.client.post(
            "/api/user/change_password",
            data=dict(new_password="curpass456", repassword="curpass456"),
        )
        resp = self.client.post(
            "/api/user/change_password",
            data=dict(new_password="curpass456", repassword="curpass456"),
        )
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))
        self.assertEqual(data.get("code"), "PASSWORD_SAME_AS_OLD")

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


class SetUsernameApiTest(unittest.TestCase):
    """设置 / 修改用户名接口测试（使用独立测试用户，避免与 ApiTest 干扰）"""

    #: 独立测试用户
    _SU_AUTH = {"username": "setusername", "uid": ""}

    @classmethod
    def setUpClass(cls):
        app = create_app()
        app.config["TESTING"] = True
        cls.app = app
        with app.app_context():
            if db.is_closed():
                db.connect()
            db.create_tables([User, Auth], safe=True)
            # 独立测试用户（幂等）
            if not has_account(cls._SU_AUTH["username"]):
                add_profile(cls._SU_AUTH["username"], "testpass123")
            auth = Auth.get(Auth.account == cls._SU_AUTH["username"])
            cls._SU_AUTH["uid"] = auth.uid

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            Auth.delete().where(
                Auth.uid == cls._SU_AUTH["uid"]
            ).execute()
            User.delete().where(User.uid == cls._SU_AUTH["uid"]).execute()
            db.close()

    def setUp(self):
        self.client = self.app.test_client()

    def _login(self, account=None):
        if account is None:
            account = self._SU_AUTH["username"]
        token = generate_jwt(account)
        self.client.set_cookie("sid", token)

    def _set_mtime(self, mtime):
        with self.app.app_context():
            Auth.update(mtime=mtime).where(
                Auth.uid == self._SU_AUTH["uid"],
                Auth.classify == "username",
            ).execute()

    def _post(self, username):
        return self.client.post(
            "/api/user/set_username", data=dict(username=username)
        )

    def test_requires_login(self):
        """未登录时禁止设置用户名"""
        data = json.loads(self._post("newuser1").data)
        self.assertFalse(data.get("success"))

    def test_username_required(self):
        """用户名缺失 → USERNAME_REQUIRED"""
        self._login()
        data = json.loads(self._post("").data)
        self.assertFalse(data.get("success"))
        self.assertEqual(data.get("code"), "USERNAME_REQUIRED")

    def test_username_invalid_format(self):
        """用户名格式非法 → USERNAME_INVALID"""
        self._login()
        data = json.loads(self._post("Ab").data)
        self.assertFalse(data.get("success"))
        self.assertEqual(data.get("code"), "USERNAME_INVALID")

    def test_username_taken(self):
        """用户名已被占用 → USERNAME_TAKEN"""
        self._login()
        data = json.loads(self._post(self._SU_AUTH["username"]).data)
        self.assertFalse(data.get("success"))
        self.assertEqual(data.get("code"), "USERNAME_TAKEN")

    def test_change_limit_within_90_days(self):
        """上次修改不足 90 天 → USERNAME_CHANGE_LIMIT"""
        self._login()
        self._set_mtime(now())
        try:
            data = json.loads(self._post("setusername3").data)
            self.assertFalse(data.get("success"))
            self.assertEqual(data.get("code"), "USERNAME_CHANGE_LIMIT")
        finally:
            self._set_mtime(0)

    def test_first_set_by_email_user(self):
        """邮箱注册用户首次设置用户名成功（changed=False）"""
        email = "setu@test.com"
        username = "setuuser"
        try:
            with self.app.app_context():
                add_profile(email, "testpass123")
                uid = Auth.get(Auth.account == email).uid
            self._login(email)
            data = json.loads(self._post(username).data)
            self.assertTrue(data.get("success"))
            self.assertFalse(data.get("data", {}).get("changed"))
            with self.app.app_context():
                acct = Auth.get(
                    (Auth.uid == uid) & (Auth.classify == "username")
                )
                self.assertEqual(acct.account, username)
        finally:
            with self.app.app_context():
                try:
                    uid = Auth.get(Auth.account == email).uid
                except Auth.DoesNotExist:
                    uid = ""
                if uid:
                    Auth.delete().where(Auth.uid == uid).execute()
                    User.delete().where(User.uid == uid).execute()

    def test_change_success(self):
        """已设置用户名用户可修改（mtime=0 视为可修改，changed=True）"""
        self._login()
        try:
            data = json.loads(self._post("setusername2").data)
            self.assertTrue(data.get("success"))
            self.assertTrue(data.get("data", {}).get("changed"))
            with self.app.app_context():
                acct = Auth.get(Auth.account == "setusername2")
                self.assertEqual(acct.uid, self._SU_AUTH["uid"])
        finally:
            with self.app.app_context():
                Auth.update(
                    account=self._SU_AUTH["username"], mtime=0
                ).where(
                    Auth.uid == self._SU_AUTH["uid"],
                    Auth.classify == "username",
                ).execute()


if __name__ == "__main__":
    unittest.main()
