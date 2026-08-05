# -*- coding: utf-8 -*-
"""
Copyright 2021 Hiroshi.tao

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

from typing import Any, Optional, Tuple, Dict, Union
from functools import wraps
from urllib.parse import urlparse, urljoin
from flask import (
    g,
    request,
    make_response,
    jsonify,
    redirect,
    url_for,
    Response,
    current_app,
)

from ..basis.vars import USR_STATE_KEY
from ..basis.mixin import GetItemMixIn
from ..basis.errors import ApiError
from ..models.user import verify_jwt, generate_jwt

signin_ep = "root.front.signin"
no_jump_ep = (signin_ep, "root.front.signout", "root.front.signup")


def is_safe_url(target: Optional[str]) -> bool:
    """检查目标URL是否安全，即是否与当前请求的host相同，且使用http或https协议。"""
    if target is None:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and test_url.netloc == ref_url.netloc


def get_referrer_url() -> Optional[str]:
    """获取上一页地址，如果上一页地址是本站的GET请求且不在no_jump_ep中，则返回该地址，否则返回None。"""
    ref = request.referrer
    if (
        ref
        and ref.startswith(request.host_url)
        and request.method == "GET"
        and request.endpoint
        and "api." not in request.endpoint
        and request.endpoint not in no_jump_ep
    ):
        return ref


def get_redirect_url(endpoint: str = signin_ep, **kwargs) -> str:
    """获取重定向地址：从 next 读取，如果没有则从 referrer 读取，最后返回默认。"""
    url = request.args.get("next")
    if not url or not is_safe_url(url):
        url = url_for(endpoint, **kwargs)
    return url


def parse_authorization(prefix: str = "Bearer") -> Optional[str]:
    """从 HTTP Authorization 请求头中提取 token。

    :param prefix: 认证模式前缀（如 ``Bearer``、``sid``）
    :returns: 提取的 token 字符串，不存在时返回 None
    """
    auth = request.headers.get("Authorization")
    if auth and auth.startswith(prefix):
        return auth.lstrip(prefix).strip()


def parse_user_state() -> Tuple[bool, GetItemMixIn]:
    """从 Cookie / Header / Query String 中解析用户登录态。

    优先级：Cookie ``sid`` → Authorization Header ``sid`` → Query String ``sid``。

    :returns: (是否登录, GetItemMixIn 字典，包含 uid 和 account)
    """
    sid = request.cookies.get(USR_STATE_KEY)
    if not sid:
        #: sessionId Header = Authorization: {USR_STATE_KEY} <jwt>
        sid = parse_authorization(USR_STATE_KEY)
        #: parse query
        if not sid:
            sid = request.args.get(USR_STATE_KEY)
    if sid and sid.count(".") == 2:
        payload = verify_jwt(sid, dump=True)
        if payload and isinstance(payload, dict):
            return True, GetItemMixIn(
                dict(uid=payload["uid"], account=payload["sub"]),
            )
    return False, GetItemMixIn({})


def set_user_state(
    sessionId: str, data: Union[str, Dict[str, Any]], max_age: int = 604800
) -> Optional[Response]:
    """设置 cookie 登录态

    :param str sessionId: 加密cookie值
    :param Union[str, Dict[str, Any]] data: 可以是重定向地址，也可以是json数据
    :rtype: Optional[Response]
    """
    if not sessionId or not data:
        return
    if isinstance(data, dict):
        response = make_response(jsonify(data))
    else:
        response = make_response(redirect(data))
    response.set_cookie(
        key=USR_STATE_KEY,
        value=sessionId,
        max_age=max_age,
        httponly=True,
        secure=False if request.url_root.split("://")[0] == "http" else True,
    )
    return response


def auto_set_user_state(
    account: str, expire: int, data: Union[str, Dict[str, Any]]
) -> Optional[Response]:
    """自动设置登录态

    :param str account: 用户账号
    :param int expire: 过期时间（秒）
    :param Union[str, Dict[str, Any]] data: 响应数据，str类型表示url，dict类型表示json数据
    :rtype: Response
    """
    if account and isinstance(expire, int) and expire > 0 and data:
        token = generate_jwt(account, expire)
        if not token:
            raise ApiError("generate cookie failed")
        ret = set_user_state(token, data, expire)
        if ret and isinstance(ret, Response):
            return ret
        else:
            raise ApiError("set cookie failed")
    else:
        raise ApiError("param error")


def clear_user_state():
    """清除用户登录态（设置过期 Cookie 清除 sid）。

    :returns: 重定向响应
    """
    res = make_response(redirect(get_redirect_url("root.front.index")))
    res.set_cookie(key=USR_STATE_KEY, value="", expires=0)
    return res


def login_required(f):
    """装饰器：要求用户已登录，否则重定向到登录页面。

    用于页面视图的路由保护。
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.signin:
            return redirect(
                get_redirect_url(
                    next=request.url if request.endpoint not in no_jump_ep else ""
                )
            )
        return f(*args, **kwargs)

    return decorated_function


def anonymous_required(f):
    """装饰器：要求用户未登录，否则重定向到首页。

    用于登录、注册等页面，防止已登录用户重复访问。
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.signin:
            return redirect(get_redirect_url("root.front.index"))
        return f(*args, **kwargs)

    return decorated_function


def apilogin_required(f):
    """装饰器：要求用户已登录，否则抛出 ApiError（403）。

    用于 API 视图的路由保护，返回 JSON 错误而非重定向。
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.signin:
            raise ApiError("no permission to access", status_code=403)
        return f(*args, **kwargs)

    return decorated_function


def get_ip() -> str:
    """获取客户端真实 IP。

    多级代理环境下，优先从 ``X-Real-IP`` 读取；其次从
    ``X-Forwarded-For`` 的最左端读取；兜底使用 ``remote_addr``。
    """
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip.strip().split(",")[0].strip()

    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.strip().split(",")[0].strip()

    return request.remote_addr


#: OAuth2 提供商图标/颜色配置，key 为 plugin_name 中 oauth2_ 之后的部分
_OAUTH2_PROVIDER_CONFIG: dict[str, dict[str, str]] = {
    "github": {"icon": "fa-brands fa-github", "color": "is-dark", "bg": "#24292e"},
    "gitee": {"icon": "fa-brands fa-git-alt", "color": "is-danger", "bg": "#c71d23"},
    "weibo": {"icon": "fa-brands fa-weibo", "color": "is-link", "bg": "#e6162d"},
    "qq": {"icon": "fa-brands fa-qq", "color": "is-success", "bg": "#12b7f5"},
    "wechat": {"icon": "fa-brands fa-weixin", "color": "is-info", "bg": "#07c160"},
}
_DEFAULT_OAUTH2_CONFIG = {"icon": "fa-solid fa-right-to-bracket", "color": "", "bg": ""}


def list_oauth2_providers(oidc_state: Optional[str] = None) -> list[dict[str, str]]:
    """获取已启用的 OAuth2 登录提供商列表（含图标、颜色配置）。"""
    result = []
    for pi in current_app.extensions["pluginkit"].get_enabled_plugins:
        if not getattr(pi.__proxy__, "__oauth2_provider__", False):
            continue
        short = (
            pi.plugin_name.split("_", 1)[1] if "_" in pi.plugin_name else pi.plugin_name
        )
        cfg = _OAUTH2_PROVIDER_CONFIG.get(short, _DEFAULT_OAUTH2_CONFIG)
        result.append(
            {
                "provider": getattr(pi.__proxy__, "__oauth2_name__", pi.plugin_name),
                "plugin_name": pi.plugin_name,
                "endpoint": url_for(
                    f"{pi.plugin_name}.login", oidc_state=oidc_state or ""
                ),
                "icon": cfg["icon"],
                "color": cfg["color"],
                "bg": cfg["bg"],
            }
        )
    return result
