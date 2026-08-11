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

import secrets
from ipaddress import ip_address, ip_network
from typing import Any, Optional, Tuple, Dict, Union
from functools import wraps
from time import strftime, time
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

from ..basis.vars import USR_STATE_KEY, PROC_NAME
from ..basis.mixin import GetItemMixIn
from ..basis.errors import ApiError
from ..models.user import verify_jwt, generate_jwt, create_session, delete_session
from .common import rdb, parse_account_classify

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

    :returns: (是否登录, GetItemMixIn 字典，包含 uid、account 和 skey)
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
                dict(
                    uid=payload["uid"],
                    account=payload["sub"],
                    skey=payload.get("skey", ""),
                ),
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
    account: str,
    expire: int,
    data: Union[str, Dict[str, Any]],
    method: str = "",
) -> Optional[Response]:
    """自动设置登录态

    登录成功时同时创建活跃会话记录，并后台异步解析 IP 地理位置和 UA 信息。

    :param str account: 用户账号
    :param int expire: 过期时间（秒）
    :param Union[str, Dict[str, Any]] data: 响应数据，str类型表示url，dict类型表示json数据
    :param str method: 登录来源（local/vcode/passkey/oauth2_github 等）
    :rtype: Response
    """
    if account and isinstance(expire, int) and expire > 0 and data:
        session_key = secrets.token_hex(32)
        token = generate_jwt(account, expire, session_key)
        if not token:
            raise ApiError("generate cookie failed")
        ret = set_user_state(token, data, expire)
        if ret and isinstance(ret, Response):
            # 同步创建活跃会话记录（基本信息）
            uid = g.user["uid"] if g.get("signin") else ""
            if not uid:
                from ..models.user import Auth
                a = Auth.get(Auth.account == account)
                uid = a.uid if a else ""
            if uid:
                client_ip = get_ip()
                create_session(
                    uid=uid,
                    session_key=session_key,
                    ip=client_ip,
                    user_agent=request.headers.get("User-Agent", ""),
                    expire_time=int(time()) + expire,
                    method=method,
                )
                # 后台线程异步更新 IP 位置和 UA 解析
                from ..libs.interface import RecordSessionInterface  # 延迟导入避免循环引用
                RecordSessionInterface(
                    uid=uid,
                    session_key=session_key,
                    ip=client_ip,
                    ua=request.headers.get("User-Agent", ""),
                    accept_lang=request.headers.get("Accept-Language", ""),
                )
            return ret
        else:
            raise ApiError("set cookie failed")
    else:
        raise ApiError("param error")


def clear_user_state():
    """清除用户登录态（设置过期 Cookie 清除 sid）。

    同时删除对应的活跃会话记录（如果存在）。

    :returns: 重定向响应
    """
    skey = g.user.get("skey", "") if g.get("user") else ""
    if skey:
        try:
            delete_session(skey)
        except Exception:
            pass
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


# 内网地址段：RFC 1918 + CGNAT + 环回 + 链路本地
_PRIVATE_NETS = [
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("100.64.0.0/10"),   # CGNAT (Tailscale/EasyTier 等)
    ip_network("127.0.0.0/8"),     # loopback
    ip_network("169.254.0.0/16"),  # link-local
]


def _is_private_ip(ip_str: str) -> bool:
    """判断 IP 是否为内网地址。"""
    try:
        addr = ip_address(ip_str.strip())
        return any(addr in net for net in _PRIVATE_NETS)
    except ValueError:
        return True  # 无法解析的 IP 视为内网（跳过）


def get_ip() -> str:
    """获取客户端真实 IP。

    优先从 ``X-Forwarded-For`` 提取第一个公网 IP，跳过中间代理的内网地址；
    若链路中全为内网 IP，则取最左端；其次从 ``X-Real-IP`` 读取；
    兜底使用 ``remote_addr``。

    适配多级代理：WAF → VPN → Ingress → Pod。
    """
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        ips = [ip.strip() for ip in xff.split(",") if ip.strip()]
        for ip in ips:
            if not _is_private_ip(ip):
                return ip
        # 全是内网 IP，返回最左端（链中第一个）
        return ips[0]

    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip.strip().split(",")[0].strip()

    return request.remote_addr or ""


def check_sms_rate_limit(account: str) -> None:
    """短信发送频率限制。

    每个手机号每天最多 10 次，全局每天最多 100 次。
    Redis 计数器 key 按天（YYYY-MM-DD）划分，自动过期。

    :param account: 手机号
    :raises ApiError: 超过限制时抛出
    """
    if parse_account_classify(account) != "mobile":
        return

    today = strftime("%Y-%m-%d")

    phone_key = f"{PROC_NAME}:sms_rl:phone:{today}:{account}"
    phone_count = int(rdb.get(phone_key) or 0)
    if phone_count >= 10:
        raise ApiError("该手机号今日发送验证码次数已达上限（10次），请明天再试")

    global_key = f"{PROC_NAME}:sms_rl:global:{today}"
    global_count = int(rdb.get(global_key) or 0)
    if global_count >= 100:
        raise ApiError("今日短信验证码发送次数已达全局上限，请明天再试")

    pipe = rdb.pipeline()
    pipe.incr(phone_key)
    pipe.expire(phone_key, 86400)
    pipe.incr(global_key)
    pipe.expire(global_key, 86400)
    pipe.execute()


#: OAuth2 提供商图标/颜色配置，key 为 plugin_name 中 oauth2_ 之后的部分
_OAUTH2_PROVIDER_CONFIG: dict[str, dict[str, str]] = {
    "github": {"icon": "fa-brands fa-github", "color": "is-dark", "bg": "#24292e"},
    "gitee": {"icon": "fa-brands fa-git-alt", "color": "is-danger", "bg": "#c71d23"},
    "weibo": {"icon": "fa-brands fa-weibo", "color": "is-link", "bg": "#e6162d"},
    "qq": {"icon": "fa-brands fa-qq", "color": "is-success", "bg": "#12b7f5"},
    "wechat": {"icon": "fa-brands fa-weixin", "color": "is-info", "bg": "#07c160"},
    "google": {"icon": "fa-brands fa-google", "color": "is-info", "bg": "#4285f4"},
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


def absolute_url(path: str) -> str:
    """将相对路径补全为绝对 URL，用于 OIDC userinfo/picture 等资源链接。

    若 path 为空或是完整 URL（http/https 开头）则直接返回；
    否则拼接当前请求的 host_url。

    :param path: 资源路径（如 /uploads/xxx.jpg）
    :returns: 绝对 URL
    """
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    return request.host_url.rstrip("/") + path


def get_rp_id() -> str:
    """获取 WebAuthn Relying Party ID。

    优先使用配置 ``PASSKEY_RP_ID``，为空时自动从请求 Host 中提取（去掉端口）。
    配置值或自动推导的值无效时抛出 PasskeyError。
    """
    from ..basis.conf import config
    from ..basis.common import is_passkey_enabled
    from ..basis.errors import PasskeyError

    rp_id = (config.get("PASSKEY_RP_ID") or "").strip()
    if rp_id:
        if not is_passkey_enabled(rp_id):
            raise PasskeyError(
                "Passkey 功能未开启：PASSKEY_RP_ID 不是有效域名"
            )
    else:
        rp_id = urlparse(request.host_url).hostname or "localhost"
        # 自动推导的值也需校验
        if not is_passkey_enabled(rp_id):
            raise PasskeyError(
                "Passkey 功能未开启：当前服务域名无法作为有效的 RP ID"
            )
    return rp_id


def get_origin() -> str:
    """获取 WebAuthn 允许的源 origin，从当前请求自动推导。

    兜底保护：当 ``request.host_url`` 在某些代理/反向代理环境下返回残缺值
    （如仅 ``"https:"``）时，通过 Host header 或 request.host 重建完整 origin。
    """
    origin = request.host_url.rstrip("/")

    # 检查 host_url 是否残缺（缺少主机名）
    parsed = urlparse(origin)
    if not parsed.hostname:
        # 从 Host header 或 request.host 重建
        host = (
            request.headers.get("Host")
            or (request.host.split(":")[0] if request.host else None)
            or "localhost"
        )
        scheme = parsed.scheme or request.scheme or "https"
        origin = "{}://{}".format(scheme, host)

    return origin
