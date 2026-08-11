# -*- coding: utf-8 -*-
"""
Copyright 2026 Hiroshi.tao

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

from flask import Blueprint, url_for, redirect, request, current_app
from authlib.integrations.flask_client import FlaskOAuth2App

from passportd.libs.interface import OAuthClient
from passportd.basis.conf import config

__plugin_name__ = "oauth2_google"
__version__ = "0.1.0"
__author__ = "staugur"
__oauth2_provider__ = True
__oauth2_name__ = "Google"
__state__ = (
    "enabled"
    if config.get("GOOGLE_CLIENT_ID") and config.get("GOOGLE_CLIENT_SECRET")
    else "disabled"
)


bp = Blueprint(__plugin_name__, __plugin_name__)

google: FlaskOAuth2App = OAuthClient.register(
    name="google",
    access_token_url="https://oauth2.googleapis.com/token",
    authorize_url="https://accounts.google.com/o/oauth2/auth",
    api_base_url="https://www.googleapis.com/oauth2/v1/",
    client_kwargs={"scope": "openid email profile"},
)  # type: ignore


@bp.route("/login")
def login():
    """重定向到 Google 授权页面，附带 OIDC state JWT（如果有）。"""
    oidc_state = request.args.get("oidc_state", "")
    kwargs = dict(state=oidc_state) if oidc_state else {}
    return google.authorize_redirect(url_for(".authorized", _external=True), **kwargs)


@bp.route("/authorized")
def authorized():
    try:
        token = google.authorize_access_token()

        # 验证令牌有效性
        if token is None or token.get("access_token") is None:
            return "Authorization failed", 403

        # 获取用户信息
        resp = google.get("userinfo", token=token)
        resp.raise_for_status()
        user_info = resp.json()
        return OAuthClient.oauth2_authorized_handler(
            google.name,
            token["access_token"],
            OAuthClient.parse_userinfo(google.name, user_info),
        )

    except Exception as e:
        return f"Error: {str(e)}", 500


def register():
    """Flask-PluginKit 注册回调，返回蓝图注册信息。

    :returns: 包含 ``bep`` 键的字典，指定蓝图和 URL 前缀 ``/oauth2/google``
    """
    return dict(
        bep=dict(blueprint=bp, prefix="/oauth2/google"),
    )
