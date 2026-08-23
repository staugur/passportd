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

from hashlib import sha256
from hmac import compare_digest, new as hmac_new
from time import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests
from flask import Blueprint, render_template, request, url_for
from flask.typing import ResponseReturnValue

from passportd.basis.conf import config
from passportd.basis.vars import (
    OAuthUserInfoType,
    PROC_NAME,
    TELEGRAM_AUTH_TTL,
    TELEGRAM_BOT_INFO_TTL,
)
from passportd.libs.interface import OAuthClient
from passportd.utils.common import is_valid_http_url, rdb

__plugin_name__ = "oauth2_telegram"
__version__ = "0.1.0"
__author__ = "staugur"
__oauth2_provider__ = True
__oauth2_name__ = "Telegram"
__state__ = "enabled" if config.get("TELEGRAM_BOT_TOKEN") else "disabled"

bp = Blueprint(__plugin_name__, __plugin_name__)

#: Telegram Bot API 基础地址
_TELEGRAM_API_BASE = "https://api.telegram.org"


def _verify_telegram_login(data: Dict[str, str], bot_token: str) -> bool:
    """校验 Telegram Login Widget 回执的签名。

    Telegram Login Widget 使用 ``secret_key = SHA256(bot_token)`` 对
    除 ``hash`` 外的所有字段（按 key 字母序，``key=value`` 每行，``\\n`` 连接）
    做 HMAC-SHA256，结果与 ``hash`` 字段比较。

    :param data: 回执字段（含 hash）
    :param bot_token: Bot Token，即签名密钥
    :returns: 签名一致返回 True
    """
    secret_key = sha256(bot_token.encode("utf-8")).digest()
    items = sorted((k, v) for k, v in data.items() if k != "hash")
    data_check_string = "\n".join(f"{k}={v}" for k, v in items)
    calc_hash = hmac_new(
        secret_key, data_check_string.encode("utf-8"), sha256
    ).hexdigest()
    return compare_digest(calc_hash, data.get("hash", ""))


def _check_auth_date(auth_date: Any, ttl: int) -> bool:
    """校验回执 ``auth_date`` 的新鲜度，防止重放攻击。

    :param auth_date: 回执中的授权时间（Unix 秒）
    :param ttl: 允许的偏差窗口（秒）
    :returns: 在窗口内返回 True
    """
    try:
        return int(time()) - int(auth_date) <= ttl
    except (TypeError, ValueError):
        return False


def _build_telegram_userinfo(data: Dict[str, str]) -> OAuthUserInfoType:
    """构造标准化 OAuth 用户信息。

    :param data: Telegram 回执字段（id/first_name/last_name/photo_url）
    :returns: 包含 account/tpid/name/picture 等字段的用户信息
    """
    tg_id = str(data.get("id", ""))
    name = " ".join(
        filter(None, [data.get("first_name", ""), data.get("last_name", "")])
    )
    return OAuthUserInfoType(
        account=OAuthClient.build_account("telegram", tg_id),
        tpid=tg_id,
        name=name,
        email="",
        picture=data.get("photo_url", "") or "",
        location="",
        gender=2,
    )


def _build_proxies() -> Optional[Dict[str, str]]:
    """根据 ``TELEGRAM_API_PROXY`` 配置构造 requests 代理参数。

    网络环境无法直连 Telegram API（如国内服务器）时配置代理；
    未配置或地址非法时返回 None（直连）。
    """
    proxy: str = config.get("TELEGRAM_API_PROXY") or ""
    if is_valid_http_url(proxy):
        return {"http": proxy, "https": proxy}
    return None


def _fetch_bot_username(bot_token: str, proxies: Optional[Dict[str, str]] = None) -> str:
    """调用 Telegram Bot API ``getMe`` 获取 Bot 用户名。

    :param bot_token: Bot Token
    :param proxies: requests 代理参数（可选）
    :returns: 成功返回 username（不带 ``@``），失败返回空串
    """
    url = f"{_TELEGRAM_API_BASE}/bot{bot_token}/getMe"
    try:
        resp = requests.get(url, timeout=10, proxies=proxies)
        resp.raise_for_status()
        return resp.json().get("result", {}).get("username", "")
    except Exception:  # noqa: BLE001
        return ""


def _get_bot_username() -> str:
    """获取 Telegram Bot 用户名，供前端 Login Widget 使用。

    查找顺序：Redis 缓存 → 环境配置 ``TELEGRAM_BOT_USERNAME`` → Bot API ``getMe``
    （结果按 ``TELEGRAM_BOT_INFO_TTL`` 缓存，避免每次打开登录页都请求 Telegram）。

    仅当未配置且请求失败时返回空串，此时登录页提示 Telegram 登录暂不可用。
    """
    key = f"{PROC_NAME}:telegram:bot_info"
    try:
        cached = str(rdb.get(key) or "")
    except Exception:  # noqa: BLE001
        cached = ""
    if cached:
        return cached
    username = config.get("TELEGRAM_BOT_USERNAME", "")
    if not username:
        bot_token = config.get("TELEGRAM_BOT_TOKEN", "")
        if bot_token:
            username = _fetch_bot_username(bot_token, _build_proxies())
            if username:
                try:
                    rdb.setex(key, TELEGRAM_BOT_INFO_TTL, username)
                except Exception:  # noqa: BLE001
                    pass
    return username


@bp.route("/login")
def login():
    """渲染内嵌 Telegram Login Widget 的页面。

    Telegram 无标准 OAuth2 授权码流程，官方提供 Login Widget：
    页面内嵌 widget 脚本，用户授权后 widget 向 ``data-auth-url``
    POST 用户信息（id/first_name/last_name/username/photo_url/auth_date/hash）。

    若携带 ``oidc_state``（OIDC Client 发起的登录），通过 query string 的
    ``state`` 透传给回调，供 ``oauth2_authorized_handler`` 解密跳转地址。
    """
    oidc_state = request.args.get("oidc_state", "")
    auth_url = url_for(".authorized", _external=True)
    if oidc_state:
        auth_url += ("&" if "?" in auth_url else "?") + urlencode(
            {"state": oidc_state}
        )
    return render_template(
        "telegram_login.j2",
        bot_username=_get_bot_username(),
        auth_url=auth_url,
    )


@bp.route("/authorized", methods=["POST"])
def authorized() -> ResponseReturnValue:
    """处理 Telegram Login Widget 的 POST 回执并完成登录/绑定。

    - 先验签（HMAC-SHA256）与 auth_date 新鲜度校验，失败返回 403；
    - 通过后构造 userinfo 交给公共回调处理（未登录则登录，已登录则绑定）。
    """
    try:
        data = request.form.to_dict()
        tg_id = data.get("id", "")
        tg_hash = data.get("hash", "")
        if not tg_id or not tg_hash:
            return "Missing authorization data", 400
        bot_token = config.get("TELEGRAM_BOT_TOKEN", "")
        if not bot_token or not _verify_telegram_login(data, bot_token):
            return "Authorization failed: invalid signature", 403
        if not _check_auth_date(data.get("auth_date", 0), TELEGRAM_AUTH_TTL):
            return "Authorization failed: auth_date expired", 403
        userinfo = _build_telegram_userinfo(data)
        return OAuthClient.oauth2_authorized_handler("telegram", userinfo)  # type: ignore[return-value]
    except Exception as e:
        return f"Error: {str(e)}", 500


def register():
    """Flask-PluginKit 注册回调，返回蓝图注册信息。

    :returns: 包含 ``bep`` 键的字典，指定蓝图和 URL 前缀 ``/oauth2/telegram``
    """
    return dict(
        bep=dict(blueprint=bp, prefix="/oauth2/telegram"),
    )
