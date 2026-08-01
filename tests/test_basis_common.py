# -*- coding: utf-8 -*-

import unittest
from time import time
from unittest.mock import patch

from passportd.basis.common import (
    new_res,
    is_true,
    raise_version,
    is_prod,
    now,
    timestamp_after_timestamp,
    check_uid_rule,
)
from passportd.basis.errors import RunError


class BasisCommonTest(unittest.TestCase):
    # ==================== new_res ====================

    def test_new_res_default(self):
        """默认参数：success=False, data为空字符串"""
        res = new_res()
        self.assertIsInstance(res, dict)
        self.assertFalse(res["success"])
        self.assertEqual(res["message"], "")

    def test_new_res_success(self):
        res = new_res(success=True)
        self.assertTrue(res["success"])

    def test_new_res_with_dict_data(self):
        res = new_res(success=True, data={"key": "value", "num": 1})
        self.assertTrue(res["success"])
        self.assertEqual(res["data"]["key"], "value")
        self.assertEqual(res["data"]["num"], 1)

    def test_new_res_with_list_data(self):
        res = new_res(success=True, data=[{"a": 1}, {"b": 2}])
        self.assertTrue(res["success"])
        self.assertEqual(len(res["data"]), 2)

    def test_new_res_with_string_data(self):
        res = new_res(success=False, data="error message")
        self.assertEqual(res["data"], "error message")

    def test_new_res_data_is_none_or_empty(self):
        # data="" 时不应设置 data 字段
        res = new_res(success=False, data="")
        self.assertNotIn("data", res)

    # ==================== is_true ====================

    def test_is_true_truthy(self):
        self.assertTrue(is_true(True))
        self.assertTrue(is_true("True"))
        self.assertTrue(is_true("true"))
        self.assertTrue(is_true("on"))
        self.assertTrue(is_true(1))
        self.assertTrue(is_true("1"))
        self.assertTrue(is_true("yes"))

    def test_is_true_falsy(self):
        self.assertFalse(is_true(False))
        self.assertFalse(is_true("False"))
        self.assertFalse(is_true("false"))
        self.assertFalse(is_true(0))
        self.assertFalse(is_true("0"))
        self.assertFalse(is_true("no"))
        self.assertFalse(is_true(""))
        self.assertFalse(is_true(None))
        self.assertFalse(is_true("random"))

    # ==================== raise_version ====================

    def test_raise_version_current(self):
        """当前 Python 版本应 >= 3.10，不应抛异常"""
        try:
            raise_version()
        except RuntimeError:
            self.fail("raise_version() raised RuntimeError unexpectedly on Python 3.10+")

    @patch("passportd.basis.common.version_info", (3, 9, 0, "final", 0))
    def test_raise_version_too_low(self):
        """Python < 3.10 时应抛出 RuntimeError"""
        with self.assertRaises(RuntimeError) as ctx:
            raise_version()
        self.assertIn("3.10", str(ctx.exception))

    # ==================== is_prod ====================

    @patch.dict("os.environ", {}, clear=True)
    def test_is_prod_default_not_prod(self):
        """无环境变量时应为非生产环境"""
        self.assertFalse(is_prod())

    @patch.dict("os.environ", {"PASSPORT_ENV": "prod"})
    def test_is_prod_pasport_env_prod(self):
        self.assertTrue(is_prod())

    @patch.dict("os.environ", {"PASSPORT_ENV": "production"})
    def test_is_prod_pasport_env_production(self):
        self.assertTrue(is_prod())

    @patch.dict("os.environ", {"PASSPORT_ENV": "dev"})
    def test_is_prod_pasport_env_dev(self):
        self.assertFalse(is_prod())

    @patch.dict("os.environ", {"FLASK_ENV": "production"})
    def test_is_prod_flask_env_production(self):
        self.assertTrue(is_prod())

    @patch.dict("os.environ", {"FLASK_ENV": "development"})
    def test_is_prod_flask_env_development(self):
        self.assertFalse(is_prod())

    @patch.dict("os.environ", {"FLASK_ENV": "development", "PASSPORT_ENV": "prod"})
    def test_is_prod_pasport_overrides_flask(self):
        """PASSPORT_ENV=prod 优先级高于 FLASK_ENV=development"""
        self.assertTrue(is_prod())

    # ==================== now ====================

    def test_now_returns_int(self):
        result = now()
        self.assertIsInstance(result, int)

    def test_now_close_to_current_time(self):
        t = time()
        n = now()
        self.assertAlmostEqual(n, t, delta=2)

    # ==================== timestamp_after_timestamp ====================

    def test_timestamp_after_seconds(self):
        base = 1000000000  # 固定时间戳
        result = timestamp_after_timestamp(base, seconds=60)
        self.assertEqual(result, base + 60)

    def test_timestamp_after_minutes(self):
        base = 1000000000
        result = timestamp_after_timestamp(base, minutes=5)
        self.assertEqual(result, base + 300)

    def test_timestamp_after_hours(self):
        base = 1000000000
        result = timestamp_after_timestamp(base, hours=1)
        self.assertEqual(result, base + 3600)

    def test_timestamp_after_days(self):
        base = 1000000000
        result = timestamp_after_timestamp(base, days=1)
        self.assertEqual(result, base + 86400)

    def test_timestamp_after_combined(self):
        base = 1000000000
        result = timestamp_after_timestamp(base, seconds=30, minutes=2, hours=1, days=0)
        self.assertEqual(result, base + 30 + 120 + 3600)

    def test_timestamp_after_default_now(self):
        """不传 timestamp 时默认使用当前时间"""
        result = timestamp_after_timestamp(seconds=10)
        self.assertIsInstance(result, int)
        self.assertGreater(result, now())

    # ==================== check_uid_rule ====================

    def test_check_uid_rule_valid(self):
        self.assertTrue(check_uid_rule("A" * 22))
        self.assertTrue(check_uid_rule("abcdefghijklmnopqrstuv"))  # 22字符

    def test_check_uid_rule_invalid_length(self):
        self.assertFalse(check_uid_rule("A" * 21))
        self.assertFalse(check_uid_rule("A" * 23))
        self.assertFalse(check_uid_rule(""))

    def test_check_uid_rule_invalid_type(self):
        self.assertFalse(check_uid_rule(123))
        self.assertFalse(check_uid_rule(None))
        self.assertFalse(check_uid_rule([]))


if __name__ == "__main__":
    unittest.main()
