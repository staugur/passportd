"""WebAuthn Passkey 功能测试。

测试范围：
- utils/common.py:  base64url 编解码、challenge 存储
- utils/web.py:      get_rp_id、get_origin
- libs/interface.py: PasskeyInterface
- models/model.py:   PasskeyCredential CRUD
- views/api.py:      Passkey API 端点

注：完整的 WebAuthn 协议流程依赖浏览器/认证器硬件交互，
    此处主要测试服务端逻辑、错误处理和参数验证。
"""

import json
import sys
import unittest
from unittest.mock import MagicMock, patch

# ---- Mock Redis（必须在导入 passportd 之前） ----
_mock_redis = MagicMock()
_mock_redis.get.return_value = None
_mock_redis.set.return_value = True
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

from passportd.app import create_app
from passportd.models.user import add_profile, generate_jwt, list_accounts
from passportd.models.model import db, User, Auth, LoginRecord, PasskeyCredential
from passportd.utils.common import (
    base64url_encode,
    base64url_decode,
    generate_passkey_challenge,
    save_passkey_challenge,
    get_passkey_challenge,
)

_AUTH = dict(username="testpassapiuser", uid="", token="")

# ---- 工具函数测试 ----


class Base64UrlTest(unittest.TestCase):
    """base64url 编解码工具测试"""

    def test_encode_decode_roundtrip(self):
        """编解码往返测试"""
        data = b"Hello WebAuthn!"
        encoded = base64url_encode(data)
        decoded = base64url_decode(encoded)
        self.assertEqual(decoded, data)

    def test_encode_no_padding(self):
        """编码结果不含 = 填充符"""
        data = b"\x00" * 10
        encoded = base64url_encode(data)
        self.assertNotIn("=", encoded)
        self.assertNotIn("+", encoded)
        self.assertNotIn("/", encoded)

    def test_decode_restores_padding(self):
        """解码时自动补齐填充符"""
        data = b"test"
        encoded = "dGVzdA"  # base64url without padding
        decoded = base64url_decode(encoded)
        self.assertEqual(decoded, data)

    def test_decode_with_minus_underscore(self):
        """解码处理 - 和 _ 字符"""
        # 包含需要 base64url 字符的短数据
        data = b"\xfb\xff\x01\x02"
        encoded = base64url_encode(data)
        decoded = base64url_decode(encoded)
        self.assertEqual(decoded, data)


class ChallengeTest(unittest.TestCase):
    """challenge 生成与缓存测试"""

    def test_generate_challenge_length(self):
        """挑战生成长度 32 字节"""
        challenge = generate_passkey_challenge()
        self.assertEqual(len(challenge), 32)
        self.assertIsInstance(challenge, bytes)

    def test_save_and_get_challenge(self):
        """挑战存取与一次性消费"""
        key = "test_user_123"
        challenge = generate_passkey_challenge()

        # 重置 mock
        _mock_redis.get.reset_mock()
        _mock_redis.set.reset_mock()
        _mock_redis.delete.reset_mock()

        # 存储
        encoded = base64url_encode(challenge)
        _mock_redis.set.return_value = True
        _mock_redis.get.return_value = encoded.encode("utf-8")
        _mock_redis.delete.return_value = True

        # save
        saved = save_passkey_challenge(key, challenge)
        self.assertTrue(saved)

        # get（应删除 key）
        result = get_passkey_challenge(key)
        self.assertEqual(result, challenge)
        _mock_redis.delete.assert_called_once()

    def test_get_nonexistent_challenge(self):
        """不存在的挑战返回 None"""
        _mock_redis.get.reset_mock()
        _mock_redis.get.return_value = None
        result = get_passkey_challenge("no_such_key")
        self.assertIsNone(result)


# ---- PasskeyInterface 测试 ----


class PasskeyInterfaceTest(unittest.TestCase):
    """PasskeyInterface 核心类测试"""

    @classmethod
    def setUpClass(cls):
        app = create_app()
        app.config["TESTING"] = True
        cls.app = app

        with app.app_context():
            if db.is_closed():
                db.connect()
            db.create_tables(
                [User, Auth, LoginRecord, PasskeyCredential], safe=True
            )
            # 创建测试用户
            add_profile(_AUTH["username"], "testpass456")
            auth = Auth.get(Auth.account == _AUTH["username"])
            _AUTH["uid"] = auth.uid
            _AUTH["token"] = generate_jwt(_AUTH["username"])

        # 预先初始化 PasskeyClient 配置（避免每次都用 request_context）
        with app.app_context():
            from passportd.libs.interface import PasskeyClient
            PasskeyClient._rp_id = "localhost"
            PasskeyClient._rp_name = "Passportd"
            PasskeyClient._origin = "http://localhost"
            PasskeyClient._initialized = True

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            PasskeyCredential.delete().where(
                PasskeyCredential.uid == _AUTH["uid"]
            ).execute()
            Auth.delete().where(Auth.account == _AUTH["username"]).execute()
            User.delete().where(User.uid == _AUTH["uid"]).execute()
            db.close()

    def setUp(self):
        self.client = self.app.test_client()
        self._login()

    def _login(self):
        self.client.set_cookie("sid", _AUTH["token"])

    def test_list_credentials_empty(self):
        """未注册 Passkey 时凭证列表为空"""
        from passportd.libs.interface import PasskeyClient

        credentials = PasskeyClient.list_credentials(_AUTH["uid"])
        self.assertIsInstance(credentials, list)
        self.assertEqual(len(credentials), 0)

    def test_delete_credential_not_found(self):
        """删除不存在的凭证返回 False"""
        from passportd.libs.interface import PasskeyClient

        ret = PasskeyClient.delete_credential(
            _AUTH["uid"], "nonexistent_cred_id"
        )
        self.assertFalse(ret)

    def test_credential_crud_flow(self):
        """凭证 CRUD 流程测试"""
        from passportd.libs.interface import PasskeyClient
        from passportd.basis.common import now
        from passportd.utils.common import base64url_encode

        # 创建模拟凭证记录
        cred_id = base64url_encode(b"test-credential-id-" + b"\x01" * 16)
        PasskeyCredential.create(
            credential_id=cred_id,
            uid=_AUTH["uid"],
            public_key=b"\x04" + b"\x00" * 64,  # 模拟 COSE 公钥
            sign_count=0,
            device_name="Chrome on macOS",
            credential_type="platform",
            ctime=now(),
        )

        # 列出凭证
        creds = PasskeyClient.list_credentials(_AUTH["uid"])
        self.assertEqual(len(creds), 1)
        self.assertEqual(creds[0]["device_name"], "Chrome on macOS")
        self.assertEqual(creds[0]["credential_id"], cred_id)

        # 删除凭证
        ret = PasskeyClient.delete_credential(_AUTH["uid"], cred_id)
        self.assertTrue(ret)

        # 确认已删除
        creds = PasskeyClient.list_credentials(_AUTH["uid"])
        self.assertEqual(len(creds), 0)


# ---- Passkey API 端点测试 ----


class PasskeyApiTest(unittest.TestCase):
    """Passkey API 端点测试"""

    @classmethod
    def setUpClass(cls):
        app = create_app()
        app.config["TESTING"] = True
        cls.app = app

        with app.app_context():
            if db.is_closed():
                db.connect()
            db.create_tables(
                [User, Auth, LoginRecord, PasskeyCredential], safe=True
            )
            add_profile(_AUTH["username"], "testpass456")
            auth = Auth.get(Auth.account == _AUTH["username"])
            _AUTH["uid"] = auth.uid
            _AUTH["token"] = generate_jwt(_AUTH["username"])

        # 预初始化 PasskeyClient 配置
        with app.app_context():
            from passportd.libs.interface import PasskeyClient
            PasskeyClient._rp_id = "localhost"
            PasskeyClient._rp_name = "Passportd"
            PasskeyClient._origin = "http://localhost"
            PasskeyClient._initialized = True

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            PasskeyCredential.delete().where(
                PasskeyCredential.uid == _AUTH["uid"]
            ).execute()
            Auth.delete().where(Auth.account == _AUTH["username"]).execute()
            User.delete().where(User.uid == _AUTH["uid"]).execute()
            db.close()

    def setUp(self):
        self.client = self.app.test_client()
        self._login()

    def _login(self):
        self.client.set_cookie("sid", _AUTH["token"])

    def test_register_options_requires_login(self):
        """未登录时获取注册选项返回错误"""
        client = self.app.test_client()
        resp = client.post("/api/passkey/register/options")
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    @patch("passportd.libs.interface.PasskeyInterface.generate_registration_options")
    def test_register_options_success(self, mock_gen):
        """登录后获取注册选项成功"""
        mock_gen.return_value = {"challenge": "test-challenge-base64url"}
        resp = self.client.post("/api/passkey/register/options")
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["challenge"], "test-challenge-base64url")

    def test_register_verify_no_data(self):
        """验证注册时缺少数据返回错误"""
        resp = self.client.post(
            "/api/passkey/register/verify",
            data=json.dumps({}),
            content_type="application/json",
        )
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    def test_login_options_public(self):
        """登录选项端点无需登录"""
        resp = self.client.post("/api/passkey/login/options")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertIn("challenge", data.get("data", {}))

    def test_login_verify_no_data(self):
        """验证登录时缺少数据返回错误"""
        resp = self.client.post(
            "/api/passkey/login/verify",
            data=json.dumps({}),
            content_type="application/json",
        )
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    def test_list_credentials_requires_login(self):
        """未登录时列出凭证返回 401"""
        client = self.app.test_client()
        resp = client.get("/api/passkey/credentials")
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    @patch("passportd.libs.interface.PasskeyInterface.list_credentials")
    def test_list_credentials_success(self, mock_list):
        """登录后列出凭证成功"""
        mock_list.return_value = [
            {
                "credential_id": "abc123",
                "device_name": "Safari on iOS",
                "credential_type": "platform",
                "sign_count": 1,
                "ctime": 1000000,
                "last_used_at": 1000100,
            }
        ]
        resp = self.client.get("/api/passkey/credentials")
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertEqual(len(data["data"]["credentials"]), 1)

    def test_delete_credential_requires_login(self):
        """未登录时删除凭证返回 401"""
        client = self.app.test_client()
        resp = client.delete("/api/passkey/credential/test-cred-id")
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))

    @patch("passportd.libs.interface.PasskeyInterface.delete_credential")
    def test_delete_credential_not_found(self, mock_delete):
        """删除不存在的凭证"""
        mock_delete.return_value = False
        resp = self.client.delete("/api/passkey/credential/nonexistent")
        data = json.loads(resp.data)
        self.assertFalse(data.get("success"))


# ---- PasskeyCredential 模型测试 ----


class PasskeyModelTest(unittest.TestCase):
    """PasskeyCredential ORM 模型测试"""

    @classmethod
    def setUpClass(cls):
        app = create_app()
        app.config["TESTING"] = True
        cls.app = app

        with app.app_context():
            if db.is_closed():
                db.connect()
            db.create_tables(
                [User, Auth, PasskeyCredential], safe=True
            )
            add_profile(_AUTH["username"], "testpass456")
            auth = Auth.get(Auth.account == _AUTH["username"])
            _AUTH["uid"] = auth.uid

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            PasskeyCredential.delete().where(
                PasskeyCredential.uid == _AUTH["uid"]
            ).execute()
            Auth.delete().where(Auth.account == _AUTH["username"]).execute()
            User.delete().where(User.uid == _AUTH["uid"]).execute()
            db.close()

    def test_create_credential(self):
        """创建 Passkey 凭证记录"""
        from passportd.basis.common import now

        with self.app.app_context():
            # 清理旧数据
            PasskeyCredential.delete().where(
                PasskeyCredential.uid == _AUTH["uid"]
            ).execute()

            cred = PasskeyCredential.create(
                credential_id="test-creds-001",
                uid=_AUTH["uid"],
                public_key=b"\x04" + b"\x01" * 64,
                sign_count=0,
                device_name="Test Device",
                credential_type="platform",
                ctime=now(),
            )

            self.assertIsNotNone(cred.id)
            self.assertEqual(cred.uid, _AUTH["uid"])

    def test_unique_credential_id(self):
        """重复 credential_id 创建失败"""
        from passportd.basis.common import now
        from peewee import IntegrityError

        with self.app.app_context():
            PasskeyCredential.delete().where(
                PasskeyCredential.uid == _AUTH["uid"]
            ).execute()

            PasskeyCredential.create(
                credential_id="test-unique-001",
                uid=_AUTH["uid"],
                public_key=b"\x04" + b"\x02" * 64,
                sign_count=0,
                device_name="Device A",
                ctime=now(),
            )

            with self.assertRaises(Exception):
                PasskeyCredential.create(
                    credential_id="test-unique-001",
                    uid=_AUTH["uid"],
                    public_key=b"\x04" + b"\x03" * 64,
                    sign_count=0,
                    device_name="Device B",
                    ctime=now(),
                )

    def test_update_sign_count(self):
        """更新签名计数器"""
        from passportd.basis.common import now

        with self.app.app_context():
            PasskeyCredential.delete().where(
                PasskeyCredential.uid == _AUTH["uid"]
            ).execute()

            cred = PasskeyCredential.create(
                credential_id="test-signcount-001",
                uid=_AUTH["uid"],
                public_key=b"\x04" + b"\x04" * 64,
                sign_count=0,
                device_name="Test Device",
                ctime=now(),
            )

            PasskeyCredential.update(sign_count=5).where(
                PasskeyCredential.credential_id == "test-signcount-001"
            ).execute()

            updated = PasskeyCredential.get(
                PasskeyCredential.credential_id == "test-signcount-001"
            )
            self.assertEqual(updated.sign_count, 5)


if __name__ == "__main__":
    unittest.main()
