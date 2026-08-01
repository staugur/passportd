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

from flask import Blueprint, url_for, redirect, request, current_app
from authlib.integrations.flask_client import FlaskOAuth2App

from passportd.libs.interface import OAuthClient
from passportd.utils.common import is_valid_http_url
from passportd.basis.conf import config

__plugin_name__ = "oauth2_github"
__version__ = "0.1.0"
__author__ = "staugur"
__oauth2_provider__ = True
__oauth2_name__ = "Github"
__state__ = (
    "enabled"
    if config.get("GITHUB_CLIENT_ID") and config.get("GITHUB_CLIENT_SECRET")
    else "disabled"
)


bp = Blueprint(__plugin_name__, __plugin_name__)

github: FlaskOAuth2App = OAuthClient.register(
    name="github",
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "user:email"},
)  # type: ignore


@bp.route("/login")
def login():
    """重定向到第三方授权页面，附带 OIDC state JWT（如果有）。"""
    oidc_state = request.args.get("oidc_state", "")
    kwargs = dict(state=oidc_state) if oidc_state else {}
    return github.authorize_redirect(url_for(".authorized", _external=True), **kwargs)


@bp.route("/authorized")
def authorized():
    try:
        proxy: str = current_app.config.get("GITHUB_CALLBACK_PROXY")  # type: ignore
        proxies = {"http": proxy, "https": proxy} if is_valid_http_url(proxy) else None

        token = github.authorize_access_token(proxies=proxies)

        # 验证令牌有效性
        if token is None or token.get("access_token") is None:
            return "Authorization failed", 403

        # 获取用户信息
        resp = github.get("user", token=token)
        resp.raise_for_status()
        user_info = resp.json()
        return OAuthClient.oauth2_authorized_handler(
            github.name,
            token["access_token"],
            OAuthClient.parse_userinfo(github.name, user_info),
        )

    except Exception as e:
        return f"Error: {str(e)}", 500


def register():
    """Flask-PluginKit 注册回调，返回蓝图注册信息。

    :returns: 包含 ``bep`` 键的字典，指定蓝图和 URL 前缀 ``/oauth2/github``
    """
    return dict(
        bep=dict(blueprint=bp, prefix="/oauth2/github"),
    )
