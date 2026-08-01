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
            raise ApiError("Some message")

    应用自动捕获ApiError异常并返回JSON类型响应::

        {"success": False, "message": "Some message"}

    :param str message: 错误信息
    :param bool success: 请求成功状态
    :param int status_code: 请求响应码，如200、403、404
    """

    def __init__(self, message: str, success: bool = False, status_code: int = 200):
        super(ApiError, self).__init__()
        self.success = success
        self.message = message
        self.status_code = status_code
        if isinstance(self.message, Exception):
            self.message = str(self.message)

    def to_dict(self):
        """将异常转为字典格式，用于 JSON 响应。

        :returns: 包含 ``success`` 和 ``message`` 的字典
        :rtype: dict
        """
        rv = dict(success=self.success, message=self.message)
        return rv


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
