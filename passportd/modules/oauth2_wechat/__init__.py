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

from typing import Any, Dict, Union
from urllib.parse import urlencode

import requests
from flask import Blueprint, redirect, url_for, request
from authlib.integrations.flask_client import FlaskOAuth2App

from passportd.libs.interface import OAuthClient
from passportd.basis.conf import config

__plugin_name__ = "oauth2_wechat"
__version__ = "0.1.0"
__author__ = "staugur"
__description__ = "Login with Wechat OAuth2"
__license__ = "Apache-2.0"
__oauth2_provider__ = True
__oauth2_name__ = "WeChat"
__state__ = (
    "enabled"
    if config.get("WECHAT_CLIENT_ID") and config.get("WECHAT_CLIENT_SECRET")
    else "disabled"
)


def _parse_wechat_userinfo(
    openid: str,
    unionid: str = "",
    nickname: str = "",
    headimgurl: str = "",
    sex: Union[str, int] = 0,
    province: str = "",
    city: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """解析微信开放平台用户信息（扫码登录）。

    微信 sex 编码：1=男 2=女 0=未知，与内部编码（0=女 1=男 2=未知）不同，需映射。

    :param openid: 微信用户唯一标识
    :param unionid: 开放平台统一标识（未绑定开放平台时为空）
    :param nickname: 昵称
    :param headimgurl: 头像 URL
    :param sex: 性别（1 男 / 2 女 / 0 未知）
    :param province: 省份
    :param city: 城市
    :returns: 标准化 OAuth 用户信息
    """
    location = " ".join(filter(None, [province, city]))
    gender_map = {"1": 1, "2": 0}
    gender = gender_map.get(str(sex), 2)
    return dict(
        account=OAuthClient.build_account("wechat", openid),
        # 有 unionid 优先使用（同一开放平台跨应用统一），否则退回 openid
        tpid=unionid or openid,
        name=nickname or "",
        picture=headimgurl or "",
        location=location,
        gender=gender,
    )


bp = Blueprint(__plugin_name__, __plugin_name__)

wechat: FlaskOAuth2App = OAuthClient.register(
    name="wechat",
    authorize_url="https://open.weixin.qq.com/connect/qrconnect",
    client_kwargs={
        "scope": "snsapi_login",
        "parse_userinfo_func": _parse_wechat_userinfo,
    },
)  # type: ignore


@bp.route("/login")
def login():
    """重定向到微信开放平台扫码登录页面，附带 OIDC state JWT（如果有）。

    微信扫码登录要求授权 URL 以 ``#wechat_redirect`` 结尾（hash 片段），
    authlib 的 ``authorize_redirect`` 无法附加，故手工构造 URL。
    """
    oidc_state = request.args.get("oidc_state", "")
    params = {
        "appid": wechat.client_id,  # type: ignore
        "redirect_uri": url_for(".authorized", _external=True),
        "response_type": "code",
        "scope": "snsapi_login",
        "state": oidc_state,
    }
    url = (
        "https://open.weixin.qq.com/connect/qrconnect?"
        + urlencode(params)
        + "#wechat_redirect"
    )
    return redirect(url)


def _wechat_fetch_token(code: str, redirect_uri: str) -> Dict[str, Any]:
    """微信获取 access_token（GET 方式，参数名为 appid/secret，非标准 OAuth2）。

    :param code: 授权码
    :param redirect_uri: 回调地址
    :returns: token 响应字典（含 access_token/openid/unionid），失败返回空 dict
    """
    token_url = "https://api.weixin.qq.com/sns/oauth2/access_token"
    token_params = {
        "grant_type": "authorization_code",
        "appid": wechat.client_id,  # type: ignore
        "secret": wechat.client_secret,  # type: ignore
        "code": code,
        "redirect_uri": redirect_uri,
    }
    token_resp = requests.get(token_url, params=token_params, timeout=15)
    token_resp.raise_for_status()
    token_data: Dict[str, Any] = token_resp.json()
    if token_data.get("errcode"):
        return {}
    return token_data


def _wechat_fetch_userinfo(access_token: str, openid: str) -> Dict[str, Any]:
    """微信获取用户基本信息（openid/nickname/sex/headimgurl 等）。

    :param access_token: 微信访问令牌
    :param openid: 用户 openid
    :returns: 用户信息字典，失败返回空 dict
    """
    userinfo_url = "https://api.weixin.qq.com/sns/userinfo"
    userinfo_params = {
        "access_token": access_token,
        "openid": openid,
        "lang": "zh_CN",
    }
    userinfo_resp = requests.get(userinfo_url, params=userinfo_params, timeout=15)
    userinfo_resp.raise_for_status()
    userinfo_data: Dict[str, Any] = userinfo_resp.json()
    if userinfo_data.get("errcode"):
        return {}
    return userinfo_data


@bp.route("/authorized")
def authorized():
    try:
        code = request.args.get("code")
        if not code:
            return "Missing authorization code", 400

        redirect_uri = url_for(".authorized", _external=True)

        # 1. 获取 access_token 与 openid
        token_data = _wechat_fetch_token(code, redirect_uri)
        access_token = token_data.get("access_token", "")
        openid = token_data.get("openid", "")
        if not access_token or not openid:
            return "Authorization failed: unable to get access_token", 403

        # 2. 获取用户信息
        user_info = _wechat_fetch_userinfo(access_token, openid)
        if not user_info:
            return "Failed to get user info", 403

        # 3. 注入 openid / unionid，供 parse_userinfo 使用
        user_info["openid"] = openid
        user_info["unionid"] = token_data.get("unionid", user_info.get("unionid", ""))

        return OAuthClient.oauth2_authorized_handler(
            wechat.name,
            OAuthClient.parse_userinfo(wechat.name, user_info),
        )

    except Exception as e:
        return f"Error: {str(e)}", 500


def register():
    """Flask-PluginKit 注册回调，返回蓝图注册信息。

    :returns: 包含 ``bep`` 键的字典，指定蓝图和 URL 前缀 ``/oauth2/wechat``
    """
    return dict(
        bep=dict(blueprint=bp, prefix="/oauth2/wechat"),
    )
