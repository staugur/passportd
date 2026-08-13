# -*- coding: utf-8 -*-
"""OIDC_INTERNAL_CLIENTS 逗号分隔配置测试。"""

import unittest

from passportd.basis.conf import _check_config_value, config
from passportd.libs.oidc import _is_internal_client


class _ConfigCheckBase(unittest.TestCase):
    """临时修改配置并断言 _check_config_value 拒绝非法值。"""

    def _assert_rejected(self, key, value):
        original = config.get(key)
        config[key] = value
        try:
            with self.assertRaises(AssertionError):
                _check_config_value(config)
        finally:
            config[key] = original


class TestLoginSecurityConfig(_ConfigCheckBase):
    """登录安全配置（LOGIN_*）类型与取值范围校验。"""

    def test_default_values_pass(self):
        self.assertIsInstance(config["LOGIN_FAIL_MAX"], int)
        self.assertIsInstance(config["LOGIN_LOCK_TIME"], int)
        self.assertIsInstance(config["LOGIN_IP_LIMIT"], int)
        self.assertIsInstance(config["LOGIN_IP_WINDOW"], int)

    def test_fail_max_zero_rejected(self):
        self._assert_rejected("LOGIN_FAIL_MAX", 0)

    def test_fail_max_negative_rejected(self):
        self._assert_rejected("LOGIN_FAIL_MAX", -1)

    def test_fail_max_non_int_rejected(self):
        self._assert_rejected("LOGIN_FAIL_MAX", "5")

    def test_lock_time_zero_rejected(self):
        self._assert_rejected("LOGIN_LOCK_TIME", 0)

    def test_lock_time_non_int_rejected(self):
        self._assert_rejected("LOGIN_LOCK_TIME", "900")

    def test_ip_limit_zero_rejected(self):
        self._assert_rejected("LOGIN_IP_LIMIT", 0)

    def test_ip_limit_non_int_rejected(self):
        self._assert_rejected("LOGIN_IP_LIMIT", "20")

    def test_ip_window_zero_rejected(self):
        self._assert_rejected("LOGIN_IP_WINDOW", 0)

    def test_ip_window_non_int_rejected(self):
        self._assert_rejected("LOGIN_IP_WINDOW", "60")


class TestMetricsConfig(_ConfigCheckBase):
    """Prometheus Metrics 配置（METRICS_*）类型与取值校验。"""

    def test_default_values_pass(self):
        self.assertIsInstance(config["METRICS_ENABLED"], bool)
        self.assertIsInstance(config["METRICS_PATH"], str)
        self.assertIsInstance(config["METRICS_CACHE_TTL"], int)
        self.assertIsInstance(config["METRICS_TOKEN"], str)

    def test_enabled_non_bool_rejected(self):
        # 环境变量 PASSPORT_METRICS_ENABLED=false 会以字符串 "false" 覆盖
        self._assert_rejected("METRICS_ENABLED", "false")

    def test_path_without_slash_rejected(self):
        self._assert_rejected("METRICS_PATH", "metrics")

    def test_path_non_str_rejected(self):
        self._assert_rejected("METRICS_PATH", 123)

    def test_cache_ttl_zero_rejected(self):
        self._assert_rejected("METRICS_CACHE_TTL", 0)

    def test_cache_ttl_non_int_rejected(self):
        self._assert_rejected("METRICS_CACHE_TTL", "30")


class TestMiscConfig(_ConfigCheckBase):
    """其余配置（LOG_LEVEL / NOTICE / 字符串类）校验。"""

    def test_invalid_log_level_rejected(self):
        self._assert_rejected("LOG_LEVEL", "TRACE")

    def test_notice_wrong_type_rejected(self):
        self._assert_rejected("NOTICE", 123)

    def test_site_title_non_str_rejected(self):
        self._assert_rejected("SITE_TITLE", ["Passport"])

    def test_host_non_str_rejected(self):
        self._assert_rejected("HOST", 123)

    def test_metrics_token_non_str_rejected(self):
        self._assert_rejected("METRICS_TOKEN", 123)

    def test_oidc_internal_clients_non_str_rejected(self):
        self._assert_rejected("OIDC_INTERNAL_CLIENTS", ["my-app"])


class TestOidcInternalClients(unittest.TestCase):
    """OIDC_INTERNAL_CLIENTS 为 str，英文逗号分隔客户端 name。"""

    def setUp(self):
        self._original = config.get("OIDC_INTERNAL_CLIENTS")

    def tearDown(self):
        config["OIDC_INTERNAL_CLIENTS"] = self._original

    def _check(self, value, names, expected):
        config["OIDC_INTERNAL_CLIENTS"] = value
        for name in names:
            self.assertEqual(_is_internal_client(name), expected)

    def test_comma_separated(self):
        self._check("my-app, your-app", ["my-app", "your-app"], True)

    def test_unknown_client_not_internal(self):
        self._check("my-app, your-app", ["third-party"], False)

    def test_spaces_around_comma(self):
        self._check(" a , b ,c ", ["a", "b", "c"], True)

    def test_empty_items_ignored(self):
        self._check("a,,b", ["a", "b"], True)

    def test_single_name(self):
        self._check("my-app", ["my-app"], True)

    def test_empty_config(self):
        self._check("", ["my-app"], False)
        self._check("   ", ["my-app"], False)

    def test_non_str_config_ignored(self):
        self._check(["my-app"], ["my-app"], False)

    def test_empty_client_name(self):
        self._check("my-app", [""], False)


if __name__ == "__main__":
    unittest.main()
