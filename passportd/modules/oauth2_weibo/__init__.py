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

from flask import Blueprint, url_for, request
from authlib.integrations.flask_client import FlaskOAuth2App

from passportd.libs.interface import OAuthClient
from passportd.basis.conf import config

__plugin_name__ = "oauth2_weibo"
__version__ = "0.1.0"
__author__ = "staugur"
__oauth2_provider__ = True
__oauth2_name__ = "Weibo"
__state__ = (
    "enabled"
    if config.get("WEIBO_CLIENT_ID") and config.get("WEIBO_CLIENT_SECRET")
    else "disabled"
)

bp = Blueprint(__plugin_name__, __plugin_name__)

weibo: FlaskOAuth2App = OAuthClient.register(
    name="weibo",
    access_token_url="https://api.weibo.com/oauth2/access_token",
    authorize_url="https://api.weibo.com/oauth2/authorize",
    api_base_url="https://api.weibo.com/2/",
    client_kwargs={"scope": ""},
)  # type: ignore


@bp.route("/login")
def login():
    """重定向到微博授权页面，附带 OIDC state JWT（如果有）。"""
    oidc_state = request.args.get("oidc_state", "")
    kwargs = dict(state=oidc_state) if oidc_state else {}
    return weibo.authorize_redirect(url_for(".authorized", _external=True), **kwargs)


@bp.route("/authorized")
def authorized():
    try:
        # 获取访问令牌（authlib 内部校验 state）
        token = weibo.authorize_access_token()

        # 验证令牌有效性
        if token is None or token.get("access_token") is None:
            return "Authorization failed", 403
        # 获取用户 uid（微博需要先获取 uid 再查用户信息）
        # 注意：微博 API 不支持 Bearer Authorization 头，access_token 必须以 query 参数传递
        uid_resp = weibo.get(
            "account/get_uid.json",
            params={"access_token": token["access_token"]},
        )
        uid_resp.raise_for_status()
        uid = uid_resp.json().get("uid")
        # 获取用户信息
        resp = weibo.get(
            "users/show.json",
            params={"uid": uid, "access_token": token["access_token"]},
        )
        resp.raise_for_status()
        user_info: Dict[str, Any] = resp.json()
        return OAuthClient.oauth2_authorized_handler(
            weibo.name,
            token["access_token"],
            OAuthClient.parse_userinfo(weibo.name, user_info),
        )

    except Exception as e:
        return f"Error: {str(e)}", 500


def register():
    """Flask-PluginKit 注册回调，返回蓝图注册信息。

    :returns: 包含 ``bep`` 键的字典，指定蓝图和 URL 前缀 ``/oauth2/weibo``
    """
    return dict(
        bep=dict(blueprint=bp, prefix="/oauth2/weibo"),
    )
