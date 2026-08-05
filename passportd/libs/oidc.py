# -*- coding: utf-8 -*-
"""
Copyright 2025 Hiroshi.tao

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

from flask import request
from authlib.oauth2 import OAuth2Error
from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant
from authlib.oauth2.rfc6749 import (
    ClientMixin,
    scope_to_list,
    list_to_scope,
    AuthorizationCodeMixin,
    TokenMixin,
    OAuth2Request,
)
from authlib.oauth2.rfc6750 import BearerTokenValidator
from authlib.oidc.core import UserInfo, OpenIDCode

from ..basis.vars import (
    PROC_NAME,
    OIDC_CODE_EXP,
    OIDC_EXP,
    OIDC_SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS,
)
from ..utils.common import now, rdb, read_rsa_private_key, compute_kid
from ..utils.web import absolute_url, get_ip
from ..models.oidc import get_oauth_client, get_oauth_token, save_oauth_token
from ..models.user import get_user_by_uid, get_user_email


def oidc_save_token(token_data: dict, request: OAuth2Request) -> bool:
    """OIDC 令牌持久化回调：将颁发的 access_token 写入数据库。

    :param token_data: 授权服务器生成的 token 数据，包含 access_token、expires_in、scope
    :param request: OAuth2 授权请求对象
    :returns: 保存成功返回 True
    """
    if request.user:
        user_id = request.user
    else:
        # client_credentials grant_type
        user_id = request.client.user_id
    client_id = request.client.client_id
    return save_oauth_token(
        user_id,
        client_id,
        token_data["access_token"],
        token_data["expires_in"],
        token_data["scope"],
        ua=request.headers.get("User-Agent", ""),
        ip=get_ip() or "",
    )


# 定义符合Authlib要求的Client类
class OIDCClient(ClientMixin, AuthorizationCodeMixin):
    """OIDC 客户端模型，实现 Authlib OAuth2 ClientMixin 接口。

    从数据库加载客户端信息，提供 redirect_uri、client_secret、scope 等校验方法。

    :param client_id: OAuth2 客户端标识
    :raises OAuth2Error: client_id 无效时抛出
    """

    def __init__(self, client_id: str):
        self.client_id = client_id
        self.client_info = get_oauth_client(client_id)
        if not self.client_info:
            raise OAuth2Error("invalid_request", "Invalid client_id")

    @property
    def client_name(self) -> str:
        """获取客户端名称，供授权页面展示。

        :returns: 客户端名称字符串
        """
        return self.client_info.get("name", "")

    def get_client_id(self) -> str:
        """获取客户端 ID。

        :returns: 客户端标识字符串
        """
        return self.client_id

    def check_redirect_uri(self, redirect_uri) -> bool:
        """校验回调 URI 是否匹配注册时配置的 redirect_uri。

        :param redirect_uri: 待校验的回调 URI
        :returns: 匹配返回 True，否则 False
        """
        return redirect_uri == self.client_info["redirect_uri"]

    def check_client_secret(self, client_secret) -> bool:
        """校验客户端密钥是否正确。

        :param client_secret: 待校验的客户端密钥
        :returns: 匹配返回 True，否则 False
        """
        return client_secret == self.client_info["client_secret"]

    def check_response_type(self, response_type) -> bool:
        """校验响应类型是否匹配。

        :param response_type: 待校验的响应类型（如 ``code``）
        :returns: 匹配返回 True，否则 False
        """
        return response_type == self.client_info["response_type"]

    def get_allowed_scope(self, scope) -> str:
        """获取请求 scope 与客户端注册 scope 的交集。

        :param scope: 请求的授权范围（空格分隔）
        :returns: 允许的授权范围字符串（交集）
        """
        if not scope:
            return ""
        allowed = set(scope_to_list(self.client_info["scope"]))  # type: ignore
        return list_to_scope([s for s in scope.split() if s in allowed])  # type: ignore

    def check_endpoint_auth_method(self, method: str, endpoint: str) -> bool:
        """校验终端认证方法是否允许。

        :param method: 认证方法（如 ``client_secret_post``）
        :param endpoint: 终端名称（如 ``token``）
        :returns: 允许返回 True，否则 False
        """
        if endpoint == "token":
            return method in OIDC_SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS
        return True

    def check_grant_type(self, grant_type: str) -> bool:
        """校验授权类型是否匹配。

        :param grant_type: 授权类型（如 ``authorization_code``）
        :returns: 匹配返回 True，否则 False
        """
        return grant_type == self.client_info["grant_type"]


# 定义符合Authlib要求的AuthorizationCode类
class OIDCAuthorizationCodeObject(AuthorizationCodeMixin):
    """OIDC 授权码对象，封装 Redis 中存储的授权码数据。

    :param code_data: 授权码相关数据字典
    """

    def __init__(self, code_data: dict):
        self.code_data = code_data

    @property
    def code(self) -> str:
        """授权码字符串。"""
        return self.code_data["code"]

    @property
    def user_id(self) -> str:
        """授权用户的 uid。"""
        return self.code_data["uid"]

    def get_redirect_uri(self) -> str:
        """获取关联的回调 URI。"""
        return self.code_data["redirect_uri"]  # type: ignore

    def get_scope(self) -> str:
        """获取授权的 scope 范围。"""
        return self.code_data["scope"]  # type: ignore

    def get_auth_time(self) -> int:
        """获取授权时间戳。"""
        return int(self.code_data["ctime"])

    def is_expired(self) -> bool:
        """判断授权码是否已过期。

        授权码有效期为 ``OIDC_CODE_EXP`` （默认 300 秒）。

        :returns: 过期返回 True，否则 False
        """
        # Check expired with 5 minute
        return (self.get_auth_time() + OIDC_CODE_EXP) < now()

    def get_nonce(self) -> str:
        """获取 OIDC nonce 值。"""
        return self.code_data["nonce"]

    def get_acr(self) -> str | None:
        """获取认证上下文类引用（ACR）。"""
        return self.code_data.get("acr")

    def get_amr(self) -> str | None:
        """获取认证方法引用（AMR）。"""
        return self.code_data.get("amr")


# 定义符合Authlib要求的Token类
class OIDCToken(TokenMixin):
    """OIDC 令牌模型，实现 Authlib TokenMixin 接口。

    从数据库加载 access_token 信息，提供过期和撤销状态检查。

    :param access_token: 访问令牌字符串
    :raises OAuth2Error: access_token 无效时抛出
    """

    def __init__(self, access_token: str):
        self.token_data = get_oauth_token(access_token)
        if not self.token_data:
            raise OAuth2Error("invalid_request", "Invalid access_token")

    def is_expired(self):
        """判断 token 是否已过期。

        :returns: 过期返回 True，否则 False
        """
        ctime: int = self.token_data["ctime"]  # type: ignore
        expires_in: int = self.token_data["expires_in"]  # type: ignore
        etime = ctime + expires_in
        return etime < now()

    def is_revoked(self) -> bool:
        """判断 token 是否已被撤销。

        :returns: 已撤销返回 True（status=0），否则 False
        """
        status = self.token_data["status"]  # type: ignore
        return status == 0

    def get_scope(self) -> str:
        """获取 token 对应的 scope。

        :returns: scope 字符串
        """
        return self.token_data["scope"]  # type: ignore


# 定义符合Authlib的授权资源保护器
class OIDCBearerTokenValidator(BearerTokenValidator):
    """Bearer Token 验证器，从 access_token 构造 OIDCToken 实例进行认证。"""

    def authenticate_token(self, token_string):  # type: ignore
        """从 token 字符串构造 OIDCToken 实例。

        :param token_string: Bearer token 字符串
        :returns: OIDCToken 实例
        """
        return OIDCToken(token_string)


class OIDCAuthorizationCodeGrant(AuthorizationCodeGrant):
    """OIDC 授权码授权流程，基于 Redis 存储授权码及过期时间。"""

    TOKEN_ENDPOINT_AUTH_METHODS = OIDC_SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS

    def _gen_code_key(self, code: str) -> str:
        """生成授权码在 Redis 中的存储键。

        :param code: 授权码字符串
        :returns: Redis key
        """
        return f"{PROC_NAME}:oidc:code:{code}"

    def save_authorization_code(self, code: str, request: OAuth2Request):
        """将授权码及关联数据保存到 Redis，并设置过期时间。

        :param code: 授权码字符串
        :param request: OAuth2 授权请求对象
        :raises OAuth2Error: 保存失败时抛出
        """
        client = request.client
        data = dict(
            code=code,
            client_id=client.client_id,
            redirect_uri=request.payload.redirect_uri,
            scope=request.payload.scope,
            uid=request.user,
            nonce=request.payload.data.get("nonce", ""),
            ctime=now(),
        )
        try:
            key = self._gen_code_key(code)
            pipe = rdb.pipeline()
            pipe.hmset(key, data)
            pipe.expire(key, OIDC_CODE_EXP)
            pipe.execute()
        except Exception as e:
            raise OAuth2Error(
                "invalid_request",
                "Failed to save authorization code: {}".format(e),
            )

    def query_authorization_code(
        self,
        code: str,
        client,
    ) -> OIDCAuthorizationCodeObject:
        """根据授权码查询并构造 OIDCAuthorizationCodeObject。

        :param code: 授权码字符串
        :param client: OAuth2 客户端实例
        :returns: 授权码对象
        :raises OAuth2Error: 授权码无效时抛出
        """
        data: dict = rdb.hgetall(self._gen_code_key(code))  # type: ignore
        if not data:
            raise OAuth2Error("invalid_request", "Invalid authorization code")
        return OIDCAuthorizationCodeObject(data)

    def delete_authorization_code(self, authorization_code):
        """删除已使用的授权码（从 Redis 中移除）。

        :param authorization_code: 授权码对象
        """
        rdb.delete(self._gen_code_key(authorization_code.code))

    def authenticate_user(self, authorization_code):
        """从授权码中提取用户 ID。

        :param authorization_code: 授权码对象
        :returns: 授权用户的 uid
        """
        return authorization_code.user_id


class OIDCOpenIDCode(OpenIDCode):
    """OIDC OpenID Code 扩展，处理 ID Token 签发中的 nonce、密钥和 claims。

    :param bool require_nonce: 是否要求 nonce
    """

    def exists_nonce(self, nonce, request):
        """返回 False 表示不检查 nonce 唯一性。

        :param nonce: nonce 值
        :param request: OAuth2 请求对象
        :returns: 始终返回 False
        """
        return False

    def get_jwks(self, client):
        """返回 JWK Set，authlib 据此在 ID Token header 中写入 ``kid``。

        ``kid`` 为 RFC 7638 指纹，密钥变更时自动变化，Client 可通过
        kid 不匹配检测密钥旋转并重新拉取 JWKS。

        :param client: OAuth2 客户端实例
        :returns: JWKS dict，包含单个 RSA 公钥的 ``keys`` 列表
        """
        prikey = read_rsa_private_key()
        from joserfc.jwk import RSAKey as JWK_RSAKey

        rsa = JWK_RSAKey.import_key(prikey)
        pub_key = rsa.as_dict(private=False)
        pub_key["kid"] = compute_kid(prikey)
        pub_key["use"] = "sig"
        pub_key["alg"] = "RS256"
        return {"keys": [pub_key]}

    def resolve_client_private_key(self, client):
        """获取用于签名 ID Token 的 RSA 私钥。

        :param client: OAuth2 客户端实例
        :returns: RSA 私钥字符串
        """
        return read_rsa_private_key()

    def get_client_algorithm(self, client):
        """获取 ID Token 签名算法。

        :param client: OAuth2 客户端实例
        :returns: 算法名称，固定为 ``RS256``
        """
        return "RS256"

    def get_client_claims(self, client):
        """构造 ID Token 的 claims（签发者、过期时间）。

        :param client: OAuth2 客户端实例
        :returns: claims 字典，包含 ``iss`` 和 ``exp``
        """
        return {
            "iss": request.url_root,
            "exp": int(now()) + OIDC_EXP,
        }

    def generate_user_info(self, user, scope):
        """根据用户和 scope 生成 UserInfo，用于生成 ID Token claims。

        从 User 模型获取用户基本信息，按 scope 分级填充 claims：

        - openid: 仅 sub
        - profile: + nickname, gender, picture, location, bio, status
        - email: + email
        - role: + role

        :param user: 用户标识（uid）
        :param scope: 授权范围字符串，以空格分隔
        :returns: UserInfo 对象
        """
        user_info = UserInfo(sub=user)
        profile = get_user_by_uid(str(user))
        if not profile:
            return user_info

        scopes = set(scope.split()) if scope else set()

        if "profile" in scopes:
            user_info["nickname"] = profile.get("nickname", "")
            user_info["gender"] = profile.get("gender", 2)
            user_info["picture"] = absolute_url(profile.get("avatar", ""))
            user_info["location"] = profile.get("location", "")
            user_info["bio"] = profile.get("bio", "")
            user_info["status"] = profile.get("status", 1)

        if "email" in scopes:
            email = get_user_email(str(user))
            if email:
                user_info["email"] = email

        if "role" in scopes:
            user_info["role"] = profile.get("role", "User")

        return user_info
