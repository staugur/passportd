# -*- coding: utf-8 -*-
"""
Copyright 2021 Hiroshi.tao

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""


class PassportError(Exception):
    """Passport 应用基础异常类，所有自定义异常均继承自此。"""
    pass


class ApiError(PassportError):
    """触发Api异常，直接中止后续执行并返回JSON格式错误。

    触发异常::

        @app.route("/test")
        def test():
            raise ApiError("Some message", code="PARAM_ERROR")

    应用自动捕获ApiError异常并返回JSON类型响应::

        {"success": False, "code": "PARAM_ERROR", "message": "Some message"}

    :param str message: 错误信息（统一英文，面向 API 消费者）
    :param str code: 错误码（可选，供前端映射为本地语言文案）
    :param bool success: 请求成功状态
    :param int status_code: 请求响应码，如200、403、404
    """

    def __init__(
        self,
        message: str,
        code: str = "",
        success: bool = False,
        status_code: int = 200,
    ):
        super(ApiError, self).__init__()
        self.success = success
        self.message = message
        self.code = code
        self.status_code = status_code
        if isinstance(self.message, Exception):
            self.message = str(self.message)

    def to_dict(self):
        """将异常转为字典格式，用于 JSON 响应。

        :returns: 包含 ``success``、``code`` 和 ``message`` 的字典
        :rtype: dict
        """
        return dict(success=self.success, code=self.code, message=self.message)


class ErrorCode:
    """API 统一错误码（与 ``ErrorCode`` 一一对应，供前端映射为中文文案）。

    规则：message 为英文，code 为稳定标识；前端通过 code 查询本地化文案，
    未映射时回退显示 message。
    """

    #: 通用
    PARAM_ERROR = "PARAM_ERROR"
    NO_PERMISSION = "NO_PERMISSION"
    RATE_LIMITED = "RATE_LIMITED"
    LOGIN_FAILED = "LOGIN_FAILED"
    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"

    #: 账号 / 密码
    ACCOUNT_REQUIRED = "ACCOUNT_REQUIRED"
    INVALID_ACCOUNT = "INVALID_ACCOUNT"
    ACCOUNT_EXISTS = "ACCOUNT_EXISTS"
    ACCOUNT_BOUND = "ACCOUNT_BOUND"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_OR_PASSWORD_REQUIRED = "ACCOUNT_OR_PASSWORD_REQUIRED"
    ACCOUNT_OR_VCODE_REQUIRED = "ACCOUNT_OR_VCODE_REQUIRED"
    INVALID_PASSWORD = "INVALID_PASSWORD"
    PASSWORD_REQUIRED = "PASSWORD_REQUIRED"
    PASSWORD_NOT_SET = "PASSWORD_NOT_SET"
    PASSWORD_MISMATCH = "PASSWORD_MISMATCH"
    PASSWORD_SAME_AS_OLD = "PASSWORD_SAME_AS_OLD"
    PASSWORD_TOO_SHORT = "PASSWORD_TOO_SHORT"

    #: 用户名
    USERNAME_REQUIRED = "USERNAME_REQUIRED"
    USERNAME_INVALID = "USERNAME_INVALID"
    USERNAME_TAKEN = "USERNAME_TAKEN"
    USERNAME_CHANGE_LIMIT = "USERNAME_CHANGE_LIMIT"

    #: 验证码
    VCODE_REQUIRED = "VCODE_REQUIRED"
    VCODE_EXPIRED = "VCODE_EXPIRED"
    VCODE_INVALID = "VCODE_INVALID"
    SMS_RATE_LIMIT = "SMS_RATE_LIMIT"
    SMS_GLOBAL_LIMIT = "SMS_GLOBAL_LIMIT"

    #: GeeTest 行为验证
    GEETEST_REQUIRED = "GEETEST_REQUIRED"
    GEETEST_FAILED = "GEETEST_FAILED"

    #: OIDC 客户端
    CLIENT_ID_REQUIRED = "CLIENT_ID_REQUIRED"
    OIDC_CLIENTS_EXIST = "OIDC_CLIENTS_EXIST"

    #: Passkey
    PASSKEY_DISABLED = "PASSKEY_DISABLED"
    CREDENTIAL_REQUIRED = "CREDENTIAL_REQUIRED"
    PASSKEY_ERROR = "PASSKEY_ERROR"

    #: 其他
    TOKEN_GENERATE_FAILED = "TOKEN_GENERATE_FAILED"
    COOKIE_FAILED = "COOKIE_FAILED"


class AuthError(PassportError):
    """认证相关异常（登录、注册、Token 验证等）。"""
    pass


class JWTError(PassportError):
    """JWT 编码/解码/验证相关异常。"""
    pass


class ParamError(PassportError):
    """参数校验异常。"""
    pass


class RunError(PassportError):
    """运行时异常（网络请求失败、外部服务错误等）。"""
    pass


class DBError(PassportError):
    """数据库操作异常。"""
    pass


class PasskeyError(PassportError):
    """WebAuthn Passkey 相关异常（注册失败、认证失败、Challenge 过期等）。"""
    pass
