# -*- coding: utf-8 -*-
"""小米开放平台 OAuth2 登录插件。

标准 OAuth2 授权码流程，通过 authlib 完成授权跳转与换 token；
小米用户信息接口（``/user/profile``）要求 ``clientId`` + ``token`` 作为
query 参数（不识别 Bearer 头），因此单独手工请求。
"""

from typing import Any

import requests
from authlib.integrations.flask_client import FlaskOAuth2App
from flask import Blueprint, request, url_for

from passportd.basis.conf import config
from passportd.libs.interface import OAuthClient

__plugin_name__ = "oauth2_xiaomi"
__version__ = "0.1.0"
__author__ = "staugur"
__description__ = "Login with Xiaomi OAuth2"
__license__ = "Apache-2.0"
__oauth2_provider__ = True
__oauth2_name__ = "Xiaomi"
__state__ = (
    "enabled"
    if config.get("XIAOMI_CLIENT_ID") and config.get("XIAOMI_CLIENT_SECRET")
    else "disabled"
)


bp = Blueprint(__plugin_name__, __plugin_name__)

XIAOMI_AUTHORIZE_URL = "https://account.xiaomi.com/oauth2/authorize"
XIAOMI_TOKEN_URL = "https://account.xiaomi.com/oauth2/token"
XIAOMI_PROFILE_URL = "https://open.account.xiaomi.com/user/profile"


def _parse_xiaomi_userinfo(
    userId: str,
    miliaoNick: str = "",
    avatarUrl: str = "",
    **kwargs: Any,
) -> dict[str, str]:
    """解析小米用户信息。

    :param userId: 小米用户唯一标识（即 tpid）
    :param miliaoNick: 小米昵称
    :param avatarUrl: 头像地址
    """
    return dict(
        account=OAuthClient.build_account("xiaomi", userId),
        tpid=userId,
        name=miliaoNick or "",
        picture=avatarUrl or "",
        location="",
        gender=2,
    )


xiaomi: FlaskOAuth2App = OAuthClient.register(
    name="xiaomi",
    access_token_url=XIAOMI_TOKEN_URL,
    authorize_url=XIAOMI_AUTHORIZE_URL,
    client_kwargs={
        "scope": "profile",
        "parse_userinfo_func": _parse_xiaomi_userinfo,
    },
)  # type: ignore


@bp.route("/login")
def login():
    """重定向到小米授权页面，附带 OIDC state JWT（如果有）。"""
    oidc_state = request.args.get("oidc_state", "")
    kwargs = dict(state=oidc_state) if oidc_state else {}
    return xiaomi.authorize_redirect(url_for(".authorized", _external=True), **kwargs)


@bp.route("/authorized")
def authorized():
    try:
        token = xiaomi.authorize_access_token()
        if token is None or not token.get("access_token"):
            return "Authorization failed", 403

        # 小米用户信息接口要求 clientId + token 作为 query 参数，不识别 Bearer 头
        resp = requests.get(
            XIAOMI_PROFILE_URL,
            params={
                "clientId": config["XIAOMI_CLIENT_ID"],
                "token": token["access_token"],
            },
            timeout=15,
        )
        if not resp.ok:
            return "Failed to get Xiaomi user info", 403

        data = resp.json().get("data") or {}
        if not data.get("userId"):
            return "Failed to get Xiaomi user id", 403

        return OAuthClient.oauth2_authorized_handler(
            xiaomi.name,
            OAuthClient.parse_userinfo(xiaomi.name, data),
        )

    except Exception as e:
        return f"Error: {str(e)}", 500


def register():
    """Flask-PluginKit 注册回调，返回蓝图注册信息。

    :returns: 包含 ``bep`` 键的字典，指定蓝图和 URL 前缀 ``/oauth2/xiaomi``
    """
    return dict(
        bep=dict(blueprint=bp, prefix="/oauth2/xiaomi"),
    )
