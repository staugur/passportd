# -*- coding: utf-8 -*-
"""Apple Sign in with Apple OAuth2 登录插件。

与微信模块类似，Apple 不走标准 authlib 换 token 流程：

- ``client_secret`` 不是固定字符串，而是调用方用 Team ID + Key ID + 私钥
  签发的 ES256 JWT（有效期最长 180 天），程序在每次换 token 时动态生成；
- 无 userinfo 端点，用户信息（``sub``/``email`` 等）包含在 token 响应返回的
  ``id_token``（JWT）中，直接解析 payload 获取；
- 授权走 ``response_mode=query``，与现有模块回调模式一致。昵称等资料仅当用户
  首次授权时在 Apple 侧选择共享才会返回（form_post 模式才回传 user 参数），
  因此 ``name`` 可能为空，用户登录后可在个人中心补充。
"""
import base64
import json
from time import time
from typing import Any, Dict

import requests
from flask import Blueprint, request, url_for
from joserfc import jwt
from joserfc.jwk import ECKey

from passportd.basis.conf import config
from passportd.basis.vars import APPLE_CLIENT_SECRET_TTL
from passportd.libs.interface import OAuthClient
from passportd.utils.common import logger

__plugin_name__ = "oauth2_apple"
__version__ = "0.1.0"
__author__ = "staugur"
__oauth2_provider__ = True
__oauth2_name__ = "Apple"
__state__ = (
    "enabled"
    if config.get("APPLE_CLIENT_ID")
    and config.get("APPLE_TEAM_ID")
    and config.get("APPLE_KEY_ID")
    and config.get("APPLE_PRIVATE_KEY")
    else "disabled"
)


bp = Blueprint(__plugin_name__, __plugin_name__)

APPLE_AUTHORIZE_URL = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"


def _parse_apple_userinfo(
    sub: str,
    email: str = "",
    email_verified: Any = False,
    is_private_email: Any = False,
    **kwargs: Any,
) -> dict[str, str]:
    """解析 Sign in with Apple 用户信息（来自 id_token 的 claims）。

    :param sub: Apple 用户唯一标识（跨应用一致，即 tpid）
    :param email: 用户邮箱，可能为空（用户拒绝共享或仅授权登录）
    """
    return dict(
        account=OAuthClient.build_account("apple", sub),
        tpid=sub,
        name="",
        email=email or "",
        picture="",
        location="",
        gender=2,
    )


apple = OAuthClient.register(
    name="apple",
    authorize_url=APPLE_AUTHORIZE_URL,
    client_kwargs={
        "scope": "name email",
        "parse_userinfo_func": _parse_apple_userinfo,
    },
)  # type: ignore


def _apple_client_secret() -> str:
    """生成 Sign in with Apple 要求的 client_secret（ES256 JWT）。

    Apple 不使用固定 client_secret，要求调用方用 Team ID、Key ID 与私钥签发
    JWT 作为 client_secret（有效期最长 180 天），程序每次换 token 时动态生成。
    """
    now_ts = int(time())
    claims = dict(
        iss=config["APPLE_TEAM_ID"],
        iat=now_ts,
        exp=now_ts + APPLE_CLIENT_SECRET_TTL,
        aud="https://appleid.apple.com",
        sub=config["APPLE_CLIENT_ID"],
    )
    key = ECKey.import_key(config["APPLE_PRIVATE_KEY"].encode("utf-8"))
    return jwt.encode(dict(alg="ES256", kid=config["APPLE_KEY_ID"]), claims, key)


def _apple_fetch_token(code: str, redirect_uri: str) -> Dict[str, Any]:
    """用授权码换取 access_token / id_token。"""
    resp = requests.post(
        APPLE_TOKEN_URL,
        data=dict(
            grant_type="authorization_code",
            code=code,
            redirect_uri=redirect_uri,
            client_id=config["APPLE_CLIENT_ID"],
            client_secret=_apple_client_secret(),
        ),
        timeout=15,
    )
    if not resp.ok:
        logger.error("apple fetch token failed: %s %s", resp.status_code, resp.text)
        return {}
    return resp.json()


def _apple_parse_id_token(id_token: str) -> Dict[str, Any]:
    """解析 id_token 的 payload（JWT 第二段，base64url）。

    id_token 来自 HTTPS 直连 Apple token 端点换取的结果，payload 内容可信，
    此处不验签，仅解出用户信息 claims（sub/email 等）。
    """
    payload = id_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


@bp.route("/login")
def login():
    """重定向到 Apple 授权页面，附带 OIDC state JWT（如果有）。"""
    oidc_state = request.args.get("oidc_state", "")
    kwargs = dict(state=oidc_state) if oidc_state else {}
    return apple.authorize_redirect(url_for(".authorized", _external=True), **kwargs)


@bp.route("/authorized")
def authorized():
    try:
        # request.values 同时兼容 query（response_mode=query）与 form 提交
        code = request.values.get("code")
        if not code:
            return "Missing authorization code", 400

        token_data = _apple_fetch_token(code, url_for(".authorized", _external=True))
        id_token = token_data.get("id_token", "")
        if not id_token:
            return "Authorization failed: unable to get id_token", 403

        claims = _apple_parse_id_token(id_token)
        return OAuthClient.oauth2_authorized_handler(
            apple.name,
            OAuthClient.parse_userinfo(apple.name, claims),
        )

    except Exception as e:
        return f"Error: {str(e)}", 500


def register():
    """Flask-PluginKit 注册回调，返回蓝图注册信息。

    :returns: 包含 ``bep`` 键的字典，指定蓝图和 URL 前缀 ``/oauth2/apple``
    """
    return dict(
        bep=dict(blueprint=bp, prefix="/oauth2/apple"),
    )
