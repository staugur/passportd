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

from typing import Any, Dict
from urllib.parse import parse_qs

import requests
from flask import Blueprint, url_for, request
from authlib.integrations.flask_client import FlaskOAuth2App

from passportd.libs.interface import OAuthClient
from passportd.basis.conf import config

__plugin_name__ = "oauth2_qq"
__version__ = "0.1.0"
__author__ = "staugur"
__oauth2_provider__ = True
__oauth2_name__ = "QQ"
__state__ = (
    "enabled"
    if config.get("QQ_CLIENT_ID") and config.get("QQ_CLIENT_SECRET")
    else "disabled"
)

bp = Blueprint(__plugin_name__, __plugin_name__)

qq: FlaskOAuth2App = OAuthClient.register(
    name="qq",
    access_token_url="https://graph.qq.com/oauth2.0/token",
    authorize_url="https://graph.qq.com/oauth2.0/authorize",
    api_base_url="https://graph.qq.com/",
    client_kwargs={"scope": "get_user_info"},
)  # type: ignore


@bp.route("/login")
def login():
    """重定向到 QQ 授权页面，附带 OIDC state JWT（如果有）。"""
    oidc_state = request.args.get("oidc_state", "")
    kwargs = dict(state=oidc_state) if oidc_state else {}
    return qq.authorize_redirect(url_for(".authorized", _external=True), **kwargs)


def _qq_fetch_token(code: str, redirect_uri: str) -> str:
    """QQ 获取 access_token（QQ 的非标准 OAuth2 GET 方式）。

    优先使用 ``fmt=json`` 参数获取 JSON 响应，降级为 URL 编码格式解析。

    :param code: 授权码
    :param redirect_uri: 回调地址
    :returns: access_token 字符串
    """
    token_url = "https://graph.qq.com/oauth2.0/token"
    token_params = {
        "grant_type": "authorization_code",
        "client_id": qq.client_id,  # type: ignore
        "client_secret": qq.client_secret,  # type: ignore
        "code": code,
        "redirect_uri": redirect_uri,
        "fmt": "json",
    }
    token_resp = requests.get(token_url, params=token_params, timeout=15)
    token_text = token_resp.text.strip()

    # 尝试 JSON 解析（fmt=json 模式）
    if token_text.startswith("{"):
        token_data = token_resp.json()
        return token_data.get("access_token", "")
    # 降级：URL 编码格式解析
    token_data = parse_qs(token_text)
    access_token_list = token_data.get("access_token", [])
    return access_token_list[0] if access_token_list else ""


def _qq_fetch_openid(access_token: str) -> str:
    """QQ 获取 openid（QQ 的非标准 JSONP 响应）。

    使用 ``fmt=json`` 参数获取纯 JSON 响应。

    :param access_token: QQ 访问令牌
    :returns: openid 字符串
    """
    openid_url = "https://graph.qq.com/oauth2.0/me"
    openid_params = {"access_token": access_token, "fmt": "json"}
    openid_resp = requests.get(openid_url, params=openid_params, timeout=15)
    openid_data = openid_resp.json()
    return openid_data.get("openid", "")


@bp.route("/authorized")
def authorized():
    try:
        code = request.args.get("code")
        if not code:
            return "Missing authorization code", 400

        redirect_uri = url_for(".authorized", _external=True)

        # 1. 获取 access_token（QQ 使用 GET 方式，非标准 OAuth2）
        access_token = _qq_fetch_token(code, redirect_uri)
        if not access_token:
            return "Authorization failed: unable to get access_token", 403
        # 2. 获取 openid（QQ 用户唯一标识）
        openid = _qq_fetch_openid(access_token)
        if not openid:
            return "Failed to get openid", 403
        # 3. 获取用户信息
        userinfo_url = "https://graph.qq.com/user/get_user_info"
        userinfo_params = {
            "access_token": access_token,
            "oauth_consumer_key": qq.client_id,  # type: ignore
            "openid": openid,
        }
        userinfo_resp = requests.get(userinfo_url, params=userinfo_params, timeout=15)
        userinfo_resp.raise_for_status()
        user_info: Dict[str, Any] = userinfo_resp.json()
        if user_info.get("ret", 0) != 0:
            return f"Failed to get user info: {user_info.get('msg', '')}", 403

        # 将 openid 注入用户信息，供 parse_userinfo 使用
        user_info["openid"] = openid

        return OAuthClient.oauth2_authorized_handler(
            qq.name,
            access_token,
            OAuthClient.parse_userinfo(qq.name, user_info),
        )

    except Exception as e:
        return f"Error: {str(e)}", 500


def register():
    """Flask-PluginKit 注册回调，返回蓝图注册信息。

    :returns: 包含 ``bep`` 键的字典，指定蓝图和 URL 前缀 ``/oauth2/qq``
    """
    return dict(
        bep=dict(blueprint=bp, prefix="/oauth2/qq"),
    )
