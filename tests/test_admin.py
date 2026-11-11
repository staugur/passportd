"""后台管理相关功能测试。

测试范围：
- models/user.py:   is_superadmin、admin_list_users 筛选/排序
- models/audit.py:  admin_list_audit_logs 过滤
- models/oidc.py:   admin_get_oauth_client、admin_delete_oauth_client
- models/stats.py:  build_admin_stats 结构

注：后台页面与 API 的鉴权依赖登录态，此处聚焦数据层逻辑。
"""

import sys
import unittest
from unittest.mock import MagicMock

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
from passportd.models.audit import admin_list_audit_logs, record_audit_log
from passportd.models.model import (
    AuditLog,
    Auth,
    OAuthAuthorization,
    OAuthClient,
    PasskeyCredential,
    User,
    UserSession,
    db,
)
from passportd.models.oidc import (
    admin_delete_oauth_client,
    admin_get_oauth_client,
)
from passportd.models.stats import build_admin_stats
from passportd.models.user import (
    add_profile,
    admin_list_users,
    admin_user_detail,
    is_superadmin,
)

_TEST_ACCOUNT = "testadminuser"
_PROBE_ACTION = "admin_unit_probe"
_PROBE_CLIENT = "admin-unit-probe-client"
_PROBE_CLIENT_ID = "client" + "0" * 18


class AdminModelTest(unittest.TestCase):
    """后台数据层逻辑测试"""

    @classmethod
    def setUpClass(cls):
        app = create_app()
        app.config["TESTING"] = True
        cls.app = app

        with app.app_context():
            if db.is_closed():
                db.connect()
            db.create_tables(
                [
                    User,
                    Auth,
                    OAuthClient,
                    OAuthAuthorization,
                    AuditLog,
                    PasskeyCredential,
                    UserSession,
                ],
                safe=True,
            )
            add_profile(_TEST_ACCOUNT, "testpwd123")
            auth = Auth.get(Auth.account == _TEST_ACCOUNT)
            cls.uid = auth.uid

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            OAuthAuthorization.delete().where(
                OAuthAuthorization.client_id == _PROBE_CLIENT_ID
            ).execute()
            OAuthClient.delete().where(
                OAuthClient.client_id == _PROBE_CLIENT_ID
            ).execute()
            AuditLog.delete().where(
                AuditLog.action == _PROBE_ACTION
            ).execute()
            Auth.delete().where(Auth.account == _TEST_ACCOUNT).execute()
            User.delete().where(User.uid == cls.uid).execute()
            db.close()

    def test_is_superadmin(self):
        """仅 superadmin 角色被识别为最高权限"""
        with self.app.app_context():
            User.update(role="superadmin").where(
                User.uid == self.uid
            ).execute()
            self.assertTrue(is_superadmin(self.uid))
            User.update(role="admin").where(User.uid == self.uid).execute()
            self.assertFalse(is_superadmin(self.uid))
            User.update(role="user").where(User.uid == self.uid).execute()
            self.assertFalse(is_superadmin(self.uid))

    def test_filter_by_login_type(self):
        """有密码 / 仅第三方 / Passkey 三种筛选"""
        with self.app.app_context():
            _, total = admin_list_users(
                keyword=_TEST_ACCOUNT, login_type="password"
            )
            self.assertGreaterEqual(total, 1)
            _, total = admin_list_users(
                keyword=_TEST_ACCOUNT, login_type="third"
            )
            self.assertEqual(total, 0)
            _, total = admin_list_users(
                keyword=_TEST_ACCOUNT, login_type="passkey"
            )
            self.assertEqual(total, 0)

    def test_filter_by_role_and_status(self):
        """角色与状态筛选不报错且结果合理"""
        with self.app.app_context():
            User.update(role="admin", status=1).where(
                User.uid == self.uid
            ).execute()
            users, total = admin_list_users(
                keyword=_TEST_ACCOUNT, role="admin", status=1
            )
            self.assertEqual(total, 1)
            self.assertEqual(users[0]["uid"], self.uid)
            _, total = admin_list_users(
                keyword=_TEST_ACCOUNT, role="superadmin"
            )
            self.assertEqual(total, 0)
            _, total = admin_list_users(
                keyword=_TEST_ACCOUNT, status=0
            )
            self.assertEqual(total, 0)

    def test_order_by_last_login(self):
        """按最后登录时间排序时附带 last_login 字段"""
        with self.app.app_context():
            users, total = admin_list_users(order="last_login", per_page=5)
            self.assertIsInstance(total, int)
            for u in users:
                self.assertIn("last_login", u)

    def test_audit_logs_action_filter(self):
        """审计日志按操作类型前缀过滤"""
        with self.app.app_context():
            record_audit_log(
                uid=self.uid,
                action=_PROBE_ACTION,
                detail={"probe": "value"},
            )
            logs, total = admin_list_audit_logs(action=_PROBE_ACTION)
            self.assertGreaterEqual(total, 1)
            self.assertEqual(logs[0]["action"], _PROBE_ACTION)
            self.assertEqual(logs[0]["detail"], {"probe": "value"})
            self.assertEqual(
                logs[0]["action_label"], logs[0]["action"]
            )

    def test_oauth_client_detail_and_delete(self):
        """客户端只读详情与后台删除（含级联清理授权）"""
        with self.app.app_context():
            OAuthClient.delete().where(
                OAuthClient.client_id == _PROBE_CLIENT_ID
            ).execute()
            OAuthClient.create(
                uid=self.uid,
                name=_PROBE_CLIENT,
                client_id=_PROBE_CLIENT_ID,
                client_secret="s" * 48,
                redirect_uri="https://example.com/cb",
                scope="openid role",
                is_internal=True,
            )
            OAuthAuthorization.create(
                uid=self.uid,
                client_id=_PROBE_CLIENT_ID,
                scope="openid",
            )

            detail = admin_get_oauth_client(_PROBE_CLIENT_ID)
            self.assertIsNotNone(detail)
            self.assertEqual(detail["auth_count"], 1)
            self.assertTrue(detail["is_internal"])
            self.assertEqual(
                detail["redirect_uris"], ["https://example.com/cb"]
            )
            self.assertIsNone(admin_get_oauth_client("short"))

            self.assertTrue(admin_delete_oauth_client(_PROBE_CLIENT_ID))
            self.assertIsNone(
                OAuthClient.get_or_none(
                    OAuthClient.client_id == _PROBE_CLIENT_ID
                )
            )
            self.assertEqual(
                OAuthAuthorization.select()
                .where(OAuthAuthorization.client_id == _PROBE_CLIENT_ID)
                .count(),
                0,
            )

    def test_user_detail(self):
        """用户详情聚合返回完整字段"""
        with self.app.app_context():
            detail = admin_user_detail(self.uid)
            self.assertIsNotNone(detail)
            self.assertEqual(detail["uid"], self.uid)
            for key in (
                "accounts",
                "sessions",
                "recent_logins",
                "recent_audits",
                "passkey_count",
                "authorization_count",
                "client_count",
            ):
                self.assertIn(key, detail)
            self.assertIsNone(admin_user_detail("not-exist-uid-0000000"))

    def test_stats_structure(self):
        """概览统计返回完整结构"""
        with self.app.app_context():
            stats = build_admin_stats()
            for key in ("kpi", "register_trend", "login_trend"):
                self.assertIn(key, stats)
            for key in (
                "total_users",
                "active_sessions",
                "oauth_clients",
                "passkey_users",
            ):
                self.assertIn(key, stats["kpi"])
            self.assertEqual(len(stats["register_trend"]), 30)
            self.assertEqual(len(stats["login_trend"]), 30)
            self.assertIsInstance(stats["suspicious"], list)


if __name__ == "__main__":
    unittest.main()
