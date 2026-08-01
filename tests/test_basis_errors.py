# -*- coding: utf-8 -*-

import unittest

from passportd.basis.errors import (
    PassportError,
    ApiError,
    AuthError,
    JWTError,
    ParamError,
    RunError,
    DBError,
)


class PassportErrorTest(unittest.TestCase):

    def test_passport_error_basic(self):
        """PassportError 基础异常行为"""
        with self.assertRaises(PassportError):
            raise PassportError()
        with self.assertRaises(PassportError):
            raise PassportError("some message")


class ApiErrorTest(unittest.TestCase):

    def test_api_error_default(self):
        err = ApiError("test message")
        self.assertEqual(err.message, "test message")
        self.assertFalse(err.success)
        self.assertEqual(err.status_code, 200)

    def test_api_error_custom_status(self):
        err = ApiError("not found", success=False, status_code=404)
        self.assertEqual(err.message, "not found")
        self.assertFalse(err.success)
        self.assertEqual(err.status_code, 404)

    def test_api_error_success(self):
        err = ApiError("ok", success=True, status_code=200)
        self.assertTrue(err.success)
        self.assertEqual(err.status_code, 200)

    def test_api_error_to_dict(self):
        err = ApiError("something wrong", success=False, status_code=400)
        d = err.to_dict()
        self.assertIsInstance(d, dict)
        self.assertFalse(d["success"])
        self.assertEqual(d["message"], "something wrong")

    def test_api_error_raises_and_caught(self):
        try:
            raise ApiError("api failed", status_code=500)
        except ApiError as e:
            self.assertEqual(e.status_code, 500)
            self.assertEqual(e.message, "api failed")
            self.assertFalse(e.success)

    def test_api_error_is_passport_error(self):
        """ApiError 应是 PassportError 的子类"""
        err = ApiError("test")
        self.assertIsInstance(err, PassportError)
        self.assertIsInstance(err, Exception)


class ErrorInheritanceTest(unittest.TestCase):
    """验证所有自定义异常的继承关系"""

    def test_auth_error_inheritance(self):
        self.assertIsInstance(AuthError(), PassportError)
        self.assertIsInstance(AuthError(), Exception)

    def test_jwt_error_inheritance(self):
        self.assertIsInstance(JWTError(), PassportError)
        self.assertIsInstance(JWTError(), Exception)

    def test_param_error_inheritance(self):
        self.assertIsInstance(ParamError(), PassportError)
        self.assertIsInstance(ParamError(), Exception)

    def test_run_error_inheritance(self):
        self.assertIsInstance(RunError(), PassportError)
        self.assertIsInstance(RunError(), Exception)

    def test_db_error_inheritance(self):
        self.assertIsInstance(DBError(), PassportError)
        self.assertIsInstance(DBError(), Exception)

    def test_all_errors_are_exception(self):
        """所有异常类都是 Exception 的子类"""
        for cls in [
            PassportError,
            ApiError,
            AuthError,
            JWTError,
            ParamError,
            RunError,
            DBError,
        ]:
            self.assertTrue(
                issubclass(cls, Exception),
                f"{cls.__name__} should be Exception subclass",
            )


class ErrorCatchHierarchyTest(unittest.TestCase):
    """验证异常捕获的层级关系"""

    def test_catch_passport_also_catches_subclass(self):
        """捕获 PassportError 也能捕获其子类异常"""

        def raise_auth():
            raise AuthError("auth failed")

        def raise_api():
            raise ApiError("api failed")

        for fn in [raise_auth, raise_api]:
            with self.subTest(fn=fn):
                with self.assertRaises(PassportError):
                    fn()

    def test_subclass_not_caught_by_sibling(self):
        """AuthError 不应被 JWTError 捕获"""
        try:
            raise AuthError("auth error")
        except JWTError:
            self.fail("AuthError should not be caught by JWTError")
        except AuthError:
            pass


if __name__ == "__main__":
    unittest.main()
