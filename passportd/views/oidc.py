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

from flask import Blueprint, request, g, render_template, url_for
from authlib.integrations.flask_oauth2 import (
    AuthorizationServer,
    ResourceProtector,
    current_token,
)
from joserfc.jwk import RSAKey
from authlib.oauth2 import OAuth2Error

from ..libs.oidc import (
    OIDCBearerTokenValidator,
    OIDCAuthorizationCodeGrant,
    OIDCOpenIDCode,
)
from ..basis.conf import config
from ..basis.vars import (
    OIDC_SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS,
    OIDC_SUPPORTED_SCOPES,
)
from ..utils.web import login_required, get_ip
from ..utils.common import compute_kid
from ..models.oidc import save_oauth_authorization
from ..models.user import get_user_by_uid, get_user_email


bp = Blueprint("oidc", "oidc")

# 初始化OAuth2服务器
server = AuthorizationServer()
server.register_grant(OIDCAuthorizationCodeGrant, [OIDCOpenIDCode(require_nonce=False)])

# 资源保护器（用于验证访问令牌）
require_oauth = ResourceProtector()
require_oauth.register_token_validator(OIDCBearerTokenValidator())


@bp.route("/.well-known/openid-configuration")
def discovery():
    """OpenID Connect Discovery 端点，返回服务端 OIDC 元数据配置。

    :returns: OIDC Provider Configuration JSON
    """
    return {
        "issuer": request.url_root,
        "authorization_endpoint": url_for(".authorize", _external=True),
        "token_endpoint": url_for(".issue_token", _external=True),
        "userinfo_endpoint": url_for(".userinfo", _external=True),
        "jwks_uri": url_for(".jwks", _external=True),
        "scopes_supported": OIDC_SUPPORTED_SCOPES,
        "response_types_supported": ["code"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "token_endpoint_auth_methods_supported": OIDC_SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS,
    }


@bp.route("/oidc/jwks")
def jwks():
    """JWKS (JSON Web Key Set) 端点，返回 RSA 公钥用于 ID Token 验证。

    返回的公钥包含 kid（RFC 7638 指纹），OIDC Client 可据此检测
    密钥变更并自动刷新缓存。

    :returns: JWKS JSON，包含 kty, n, e, kid, use, alg
    """
    prikey = config["OIDC_RSA_PRIVATE_KEY"]
    with open(prikey, "r") as fp:
        private_key = fp.read()
    rsa = RSAKey.import_key(private_key)
    pub_key = rsa.as_dict(private=False)
    pub_key["kid"] = compute_kid(private_key)
    pub_key["use"] = "sig"
    pub_key["alg"] = "RS256"
    return {"keys": [pub_key]}


@bp.route("/oidc/authorize", methods=["GET", "POST"])  # type: ignore
@login_required
def authorize():
    """
    处理OAuth 2.0授权请求的视图函数。

    该函数根据HTTP请求方法（GET或POST）执行不同的逻辑：
    - GET请求：获取用户的授权同意（consent grant），并渲染授权页面。
    - POST请求：根据用户的操作（批准或拒绝）创建授权响应。

    参数：
        无显式参数，但依赖于Flask的全局对象（如`g.user`和`request`）。

    返回值：
        - GET请求：渲染的授权页面模板（authorize.j2），包含授权范围和授权信息。
        - POST请求：OAuth 2.0授权响应，可能是授权码或错误响应。

    异常：
        - 可能抛出OAuth2Error异常，由`server.handle_error_response`处理。

    作用范围：
        导出的API函数，通常用于OAuth 2.0授权端点的实现。
    """
    current_user = g.user["uid"]
    if request.method == "GET":
        try:
            grant = server.get_consent_grant(end_user=current_user)
        except OAuth2Error as e:
            return server.handle_error_response(request, e)  # type: ignore

        scope = grant.client.get_allowed_scope(grant.request.scope)
        return render_template(
            "authorize.j2",
            grant=grant,
            scope=scope,
        )
    else:
        # POST authorization response
        action = request.form.get("action")
        # granted by resource owner
        grant_user = current_user if action == "approve" else None
        try:
            grant = server.get_consent_grant(end_user=current_user)
        except OAuth2Error as e:
            return server.handle_error_response(request, e)

        # 仅 approved 时保存授权记录
        if action == "approve":
            try:
                save_oauth_authorization(
                    uid=current_user,
                    client_id=grant.client.client_id,
                    scope=grant.request.scope,
                    ip=get_ip() or "",
                    ua=request.headers.get("User-Agent", ""),
                )
            except Exception:
                pass  # 记录失败不影响授权流程

        return server.create_authorization_response(grant=grant, grant_user=grant_user)


@bp.post("/oidc/token")  # type: ignore
def issue_token():
    """OAuth 2.0 Token 端点：用授权码换取 access_token 和 id_token。

    :returns: Token 响应 JSON
    """
    return server.create_token_response()


@bp.route("/oidc/userinfo")
@require_oauth("openid")
def userinfo():
    """OIDC UserInfo 端点：根据 token 的 scope 分层返回用户信息。

    需要 ``openid`` scope 授权。返回字段按 scope 分级：

    - ``openid``: 仅 sub(uid)
    - ``+ profile``: + nickname, bio, gender, picture, location, status
    - ``+ email``: + email
    - ``+ role``: + role

    :returns: 用户信息 JSON
    """
    uid = current_token.token_data.get("uid")
    profile = get_user_by_uid(uid) if uid else None
    if not profile:
        return {"sub": uid}

    token_scope = current_token.get_scope()
    scopes = set(token_scope.split()) if token_scope else set()

    result: dict = {"sub": profile["uid"]}

    if "profile" in scopes:
        result.update(
            {
                "nickname": profile["nickname"],
                "bio": profile["bio"],
                "gender": profile["gender"],
                "picture": profile["avatar"],
                "location": profile["location"],
                "status": profile["status"],
            }
        )

    if "email" in scopes:
        email = get_user_email(uid)
        if email:
            result["email"] = email

    if "role" in scopes:
        result["role"] = profile["role"]

    return result
