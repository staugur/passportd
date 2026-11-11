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

import csv
from functools import wraps
from io import StringIO
from time import localtime, strftime, time

from flask import Blueprint, abort, g, request, Response
from werkzeug.security import check_password_hash

from ..basis.common import is_passkey_enabled, new_res
from ..basis.conf import config
from ..basis.errors import (
    ApiError,
    AuthError,
    ErrorCode,
    ParamError,
    PasskeyError,
    PassportError,
)
from ..basis.vars import JWE_HEADER, PROC_NAME
from ..libs.interface import (
    NoticeClient,
    PasskeyClient,
    RecordLoginInterface,
    UploadInterface,
    VCodeInterface,
)
from ..libs.geetest import GeetestLib, get_bypass_cache
from ..models.audit import (
    admin_list_audit_logs,
    list_audit_logs,
    record_audit_log,
)
from ..models.model import User
from ..models.oidc import (
    admin_delete_oauth_client,
    admin_get_oauth_client,
    admin_set_client_internal,
    count_oauth_authorizations,
    create_oauth_client,
    delete_oauth_authorization,
    delete_oauth_client,
    list_oauth_authorizations_by_user,
    list_oauth_clients,
    list_oauth_clients_page,
    update_oauth_client,
)
from ..models.user import (
    add_account,
    admin_list_login_records,
    admin_list_users,
    admin_user_detail,
    change_password,
    count_superadmins,
    delete_account,
    delete_user_data,
)
from ..models.user import get_account as get_auth
from ..models.user import (
    get_login_session_expire,
    get_user_by_uid,
    has_account,
    has_uid,
    list_accounts,
    list_active_sessions,
    list_login_records,
    register_vcode,
    set_login_session_expire,
    set_platform_roles,
    set_username,
    update_profile,
)
from ..utils.common import (
    generate_digital_verification_code,
    normalize_builtin_role,
    parse_account_classify,
    parse_encrypted_password,
    rdb,
    read_rsa_public_key,
    username_check,
)
from ..utils.web import (
    apilogin_required,
    api_admin_required,
    api_superadmin_required,
    auto_set_user_state,
    check_sms_rate_limit,
    get_ip,
    ip_rate_limit,
    resolve_login_source,
)

bp = Blueprint("api", "api")


@bp.get("/key")
def public_key():
    """获取 RSA 公钥及 JWE header 信息，用于前端密码加密。

    :returns: 包含 ``header`` （JWE 头）和 ``key`` （公钥 PEM）的 JSON 响应
    """
    try:
        key = read_rsa_public_key()
    except Exception as e:
        raise ApiError(str(e), code=ErrorCode.PARAM_ERROR)
    else:
        return new_res(
            success=True,
            data=dict(header=JWE_HEADER, key=key),  # type: ignore
        )


@bp.get("/user/audit_log")
@apilogin_required
def user_audit_log():
    """获取当前用户的安全审计日志。

    返回用户最近 10 条敏感操作记录（注册、绑定/解绑、Passkey、OIDC 客户端管理等），
    按时间倒序排列。

    :returns: data 中包含 audit_logs 列表
    """
    uid = g.user["uid"]
    logs = list_audit_logs(uid=uid, limit=10)
    return new_res(success=True, data=dict(audit_logs=logs))


@bp.get("/user/sessions")
@apilogin_required
def user_sessions():
    """获取当前用户的活跃会话列表。

    返回未过期的活跃会话，包含设备、IP（含地理位置）、浏览器、登录时间，
    以及服务端计算的剩余有效期（秒），避免依赖客户端时钟。

    :returns: data 中包含 sessions 列表
    """
    uid = g.user["uid"]
    now_ts = int(time())
    sessions = list_active_sessions(uid=uid)
    for s in sessions:
        # 移除前端不需要的字段，并补充剩余有效期
        s.pop("id", None)
        s.pop("user_agent", None)
        expire_time = int(s.get("expire_time") or 0)
        s["expire_in"] = max(0, expire_time - now_ts)
    return new_res(success=True, data=dict(sessions=sessions))


@bp.put("/user/session/expire")
@apilogin_required
def user_session_expire_set():
    """设置使用 Passkey 或第三方账号登录时的会话保持时长。

    :form expire: 会话保持时长（秒），需为可选档位之一
    :returns: 设置生效的时长
    """
    uid = g.user["uid"]
    expire = request.form.get("expire", type=int)
    if not expire:
        raise ApiError("expire is required", code=ErrorCode.PARAM_ERROR)
    try:
        value = set_login_session_expire(uid, expire)
    except ParamError:
        raise ApiError(
            "invalid session expire value", code=ErrorCode.PARAM_ERROR
        )
    except AuthError:
        raise ApiError("user not found", code=ErrorCode.USER_NOT_FOUND)
    record_audit_log(
        uid=uid,
        action="session_expire_set",
        detail={"expire": value},
        ip=get_ip(),
        user_agent=request.headers.get("User-Agent", ""),
    )
    return new_res(success=True, data=dict(expire=value))


@bp.post("/user/change_password")
@apilogin_required
def change_pwd():
    """修改本地账号密码（需已登录）。

    支持明文密码和 RSA 加密密码。

    :form new_password: 新密码（明文）
    :form repassword: 确认新密码（明文）
    :form encrypted_new_password: 加密后的新密码（JWE 格式，优先使用）
    :form encrypted_repassword: 加密后的确认新密码（JWE 格式，优先使用）
    :returns: 操作结果 JSON
    """
    data = request.form.to_dict()
    uid = g.user["uid"]
    account = g.user["account"]

    # 解密密码（优先加密格式）
    new_pwd = parse_encrypted_password(
        data.get("encrypted_new_password", "")
    ) or data.get("new_password", "")
    repassword = parse_encrypted_password(
        data.get("encrypted_repassword", "")
    ) or data.get("repassword", "")

    if not new_pwd:
        raise ApiError("new_password is required", code=ErrorCode.PASSWORD_REQUIRED)
    if new_pwd != repassword:
        raise ApiError(
            "new_password and repassword do not match", code=ErrorCode.PASSWORD_MISMATCH
        )
    if len(new_pwd) < 6:
        raise ApiError(
            "new_password must be at least 6 characters",
            code=ErrorCode.PASSWORD_TOO_SHORT,
        )

    try:
        ret = change_password(uid, account, new_pwd)
    except ParamError as e:
        # 依据 models.change_password 的校验点映射错误码，
        # 避免所有场景都提示“请输入密码”造成误导
        msg = str(e)
        if "Only local accounts" in msg:
            raise ApiError(msg, code=ErrorCode.LOCAL_ACCOUNT_ONLY)
        if "different from current password" in msg:
            raise ApiError(msg, code=ErrorCode.PASSWORD_SAME_AS_OLD)
        if "6-32 characters" in msg:
            raise ApiError(msg, code=ErrorCode.PASSWORD_TOO_SHORT)
        raise ApiError(msg, code=ErrorCode.PASSWORD_REQUIRED)
    except AuthError as e:
        raise ApiError(str(e), code=ErrorCode.PASSWORD_REQUIRED)
    else:
        record_audit_log(
            uid=uid,
            action="change_password",
            detail={},
            ip=get_ip(),
            user_agent=request.headers.get("User-Agent", ""),
        )
        return new_res(success=ret)


@bp.get("/user/login_history")
@apilogin_required
def login_history():
    """获取当前用户最近登录记录。

    :returns: data 中包含 login_history 列表（最近 10 条，按时间倒序）
    """
    uid = g.user["uid"]
    records = list_login_records(uid, limit=10)
    return new_res(success=True, data=dict(login_history=records))


@bp.post("/upload")
@apilogin_required
def upload():
    """上传 base64 格式图片。

    :form base64: Data URI 格式的 base64 图片编码
    :returns: 上传结果 JSON，data 中包含图片 URL
    """
    img_base64 = request.form.get("base64")
    # img_file = request.files.get("file")
    if img_base64:
        upins = UploadInterface()
        return upins.upload_base64_image(img_base64)
    else:
        return abort(400)


#: OIDC 客户端回调地址对应的表单字段名（最多 5 个）
_REDIRECT_URI_FIELDS = (
    "redirect_uri",
    "redirect_uri2",
    "redirect_uri3",
    "redirect_uri4",
    "redirect_uri5",
)


def _collect_redirect_uris_from_form(form) -> list:
    """从表单收集非空回调地址字段，返回列表（最多 5 个）。

    :param form: Flask 请求表单（ImmutableMultiDict）
    :returns: 非空回调地址字符串列表
    """
    return [
        form.get(field, "").strip()
        for field in _REDIRECT_URI_FIELDS
        if form.get(field, "").strip()
    ]


@bp.route("/oidc/client", methods=["POST", "GET", "PUT", "DELETE"])
@apilogin_required
def oidc_client():
    """OIDC 客户端管理接口（CRUD）。

    - **GET**: 列出当前用户的所有 OIDC 客户端（含授权用户数）
    - **POST**: 创建新 OIDC 客户端
    - **PUT**: 更新 OIDC 客户端信息
    - **DELETE**: 删除 OIDC 客户端及关联 Token

    :form name: 客户端名称（POST / PUT）
    :form redirect_uri: 回调 URI（POST / PUT）
    :form client_id: 客户端 ID（PUT / DELETE）
    :form scope: 授权范围（POST / PUT）
    :form homepage: 主页 URL
    :form bio: 描述
    :returns: 操作结果 JSON
    """
    uid = g.user["uid"]
    if request.method == "GET":
        ret = list_oauth_clients(uid=uid)
        # 附加每个客户端的授权用户数
        for client in ret:
            client["auth_count"] = count_oauth_authorizations(str(client["client_id"]))
        res = new_res(success=True, data=ret)
        return res

    if request.method == "DELETE":
        client_id = request.form.get("client_id", "")
        if not client_id:
            raise ApiError("client_id is required", code=ErrorCode.CLIENT_ID_REQUIRED)
        try:
            ret = delete_oauth_client(uid=uid, client_id=client_id)
        except PassportError as e:
            raise ApiError(str(e), code=ErrorCode.PARAM_ERROR)
        else:
            record_audit_log(
                uid=uid,
                action="oidc_client_delete",
                detail={"client_id": client_id},
                ip=get_ip(),
                user_agent=request.headers.get("User-Agent", ""),
            )
            return new_res(success=True, data=dict(deleted=ret))

    if request.method == "PUT":
        client_id = request.form.get("client_id", "")
        if not client_id:
            raise ApiError("client_id is required", code=ErrorCode.CLIENT_ID_REQUIRED)
        name = request.form.get("name", "")
        bio = request.form.get("bio", "")
        homepage = request.form.get("homepage", "")
        redirect_uris = _collect_redirect_uris_from_form(request.form)
        scope = request.form.get("scope", "")
        try:
            ret = update_oauth_client(
                uid=uid,
                client_id=client_id,
                name=name,
                bio=bio,
                homepage=homepage,
                redirect_uris=redirect_uris if redirect_uris else None,
                scope=scope,
            )
        except PassportError as e:
            raise ApiError(str(e), code=ErrorCode.PARAM_ERROR)
        else:
            record_audit_log(
                uid=uid,
                action="oidc_client_update",
                detail={"client_id": client_id, "name": name},
                ip=get_ip(),
                user_agent=request.headers.get("User-Agent", ""),
            )
            return new_res(success=True, data=ret)

    # POST: create
    name = request.form.get("name", "")
    bio = request.form.get("bio", "")
    homepage = request.form.get("homepage", "")
    redirect_uris = _collect_redirect_uris_from_form(request.form)
    scope = request.form.get("scope", "")
    try:
        ret = create_oauth_client(
            uid=uid,
            name=name,
            bio=bio,
            homepage=homepage,
            redirect_uris=redirect_uris,
            scope=scope,
        )
    except PassportError as e:
        raise ApiError(str(e), code=ErrorCode.PARAM_ERROR)
    else:
        record_audit_log(
            uid=uid,
            action="oidc_client_create",
            detail={"client_id": ret.get("client_id", ""), "name": name},
            ip=get_ip(),
            user_agent=request.headers.get("User-Agent", ""),
        )
        res = new_res(success=True, data=ret)
        return res


@bp.route("/user/oauth/authorizations", methods=["GET", "DELETE"])
@apilogin_required
def user_oauth_authorizations():
    """用户 OIDC 授权管理接口。

    - **GET**: 列出当前用户所有已授权的 OIDC 客户端
    - **DELETE**: 撤销对指定客户端的授权（同时清除关联 Token）

    :form client_id: 客户端 ID（DELETE 时必填）
    :returns: 操作结果 JSON
    """
    uid = g.user["uid"]
    if request.method == "GET":
        limit = int(request.args.get("limit", 10))
        ret = list_oauth_authorizations_by_user(uid=uid, limit=limit)
        return new_res(success=True, data=ret)

    # DELETE
    client_id = request.form.get("client_id", "")
    if not client_id:
        raise ApiError("client_id is required", code=ErrorCode.CLIENT_ID_REQUIRED)
    try:
        ret = delete_oauth_authorization(uid=uid, client_id=client_id)
    except PassportError as e:
        raise ApiError(str(e), code=ErrorCode.PARAM_ERROR)
    else:
        record_audit_log(
            uid=uid,
            action="oidc_auth_revoke",
            detail={"client_id": client_id},
            ip=get_ip(),
            user_agent=request.headers.get("User-Agent", ""),
        )
        return new_res(success=True, data=dict(deleted=ret))


@bp.post("/send_login_vcode")
@ip_rate_limit
def send_login_vcode():
    """发送登录验证码（邮箱或短信）。

    根据账号格式自动判断为邮箱或手机号，通过对应渠道发送 6 位数字验证码。
    未注册账号也可发送（验证码登录即注册），同一账号 60 秒内不可重复请求，
    验证码 5 分钟内有效。

    :form account: 邮箱地址或手机号（必填）
    :returns: 发送结果 JSON
    """
    account = request.form.get("account", "").strip()
    if not account:
        raise ApiError("account is required", code=ErrorCode.ACCOUNT_REQUIRED)

    classify = parse_account_classify(account)
    if classify not in ("email", "mobile"):
        raise ApiError("invalid email or mobile number", code=ErrorCode.INVALID_ACCOUNT)

    check_sms_rate_limit(account)

    # 60s 内同一账号不可重复发送
    rl_key = f"{PROC_NAME}:login_vcode_rl:{account}"
    if rdb.exists(rl_key):
        raise ApiError(
            "too many requests, please retry in 60 seconds", code=ErrorCode.RATE_LIMITED
        )

    code = generate_digital_verification_code()
    vi = VCodeInterface()

    if classify == "email":
        ret = vi.send_email(account, code)
    else:
        ret = vi.send_sms(account, code)

    if ret["success"] is True:
        # 验证码写入 Redis，5 分钟有效
        rdb.setex(f"{PROC_NAME}:login_vcode:{account}", 300, code)
        rdb.setex(rl_key, 60, "1")

    return ret


@bp.post("/user/send_bind_vcode")
@apilogin_required
def user_send_bind_vcode():
    """发送绑定验证码（邮箱或短信）。

    向待绑定的邮箱或手机号发送 6 位数字验证码。
    该账号必须未被注册，同一账号 60 秒内不可重复请求，验证码 5 分钟内有效。

    :form account: 邮箱地址或手机号（必填）
    :returns: 发送结果 JSON
    """
    account = request.form.get("account", "").strip()
    if not account:
        raise ApiError("account is required", code=ErrorCode.ACCOUNT_REQUIRED)

    classify = parse_account_classify(account)
    if classify not in ("email", "mobile"):
        raise ApiError("invalid email or mobile number", code=ErrorCode.INVALID_ACCOUNT)

    if has_account(account):
        raise ApiError(
            "account already bound, please use another one",
            code=ErrorCode.ACCOUNT_BOUND,
        )

    check_sms_rate_limit(account)

    rl_key = f"{PROC_NAME}:bind_vcode_rl:{account}"
    if rdb.exists(rl_key):
        raise ApiError(
            "too many requests, please retry in 60 seconds", code=ErrorCode.RATE_LIMITED
        )

    code = generate_digital_verification_code()
    vi = VCodeInterface()

    if classify == "email":
        ret = vi.send_email(account, code)
    else:
        ret = vi.send_sms(account, code)

    if ret["success"] is True:
        rdb.setex(f"{PROC_NAME}:bind_vcode:{account}", 300, code)
        rdb.setex(rl_key, 60, "1")

    return ret


@bp.post("/user/bind_account")
@apilogin_required
def user_bind_account():
    """绑定邮箱或手机号接口。

    校验用户提交的验证码，验证通过后将账号添加到当前用户的 Auth 记录。

    :form account: 邮箱地址或手机号（必填）
    :form code: 验证码（必填）
    :returns: 绑定结果 JSON
    """
    uid = g.user["uid"]
    account = request.form.get("account", "").strip()
    code = request.form.get("code", "").strip()

    if not account or not code:
        raise ApiError(
            "account and verification code are required",
            code=ErrorCode.ACCOUNT_OR_VCODE_REQUIRED,
        )

    classify = parse_account_classify(account)
    if classify not in ("email", "mobile"):
        raise ApiError(
            "only email or mobile number can be bound", code=ErrorCode.INVALID_ACCOUNT
        )

    if has_account(account):
        raise ApiError(
            "account already bound, please use another one",
            code=ErrorCode.ACCOUNT_BOUND,
        )

    stored = rdb.get(f"{PROC_NAME}:bind_vcode:{account}")
    if isinstance(stored, bytes):
        stored = stored.decode()
    if not stored or stored != code:
        raise ApiError(
            "invalid or expired verification code", code=ErrorCode.VCODE_INVALID
        )

    try:
        add_account(uid=uid, account=account)
    except PassportError as e:
        raise ApiError(str(e), code=ErrorCode.ACCOUNT_BOUND)
    else:
        rdb.delete(f"{PROC_NAME}:bind_vcode:{account}")
        record_audit_log(
            uid=uid,
            action="bind_account",
            detail={"account": account, "type": classify},
            ip=get_ip(),
            user_agent=request.headers.get("User-Agent", ""),
        )
        return new_res(success=True, data=dict(account=account))


@bp.post("/user/set_username")
@apilogin_required
def user_set_username():
    """设置或修改用户名接口。

    每个用户仅保留一条 username 类型的 Auth 记录；修改后 3 个月内
    仅可再次修改一次（通过 Auth.mtime 校验）。

    :form username: 用户名（必填，小写字母开头，3-32 位小写字母/数字/下划线）
    :returns: 设置结果 JSON
    """
    uid = g.user["uid"]
    username = request.form.get("username", "").strip()
    if not username:
        raise ApiError("username is required", code=ErrorCode.USERNAME_REQUIRED)
    if not username_check(username):
        raise ApiError("invalid username format", code=ErrorCode.USERNAME_INVALID)
    if has_account(username):
        raise ApiError("username already exists", code=ErrorCode.USERNAME_TAKEN)
    try:
        ret = set_username(uid=uid, username=username)
    except PassportError as e:
        raise ApiError(str(e), code=ErrorCode.USERNAME_CHANGE_LIMIT)
    else:
        record_audit_log(
            uid=uid,
            action="set_username",
            detail={"username": username, "changed": ret["changed"]},
            ip=get_ip(),
            user_agent=request.headers.get("User-Agent", ""),
        )
        return new_res(success=True, data=ret)


@bp.post("/user/unbind_account")
@apilogin_required
def user_unbind_account():
    """解绑邮箱、手机号、用户名或第三方账号接口。

    验证当前密码，通过后删除该 Auth 记录。

    :form account: 邮箱地址、手机号、用户名或第三方账号（必填）
    :form password: 当前密码（必填）
    :returns: 解绑结果 JSON
    """
    uid = g.user["uid"]
    account = request.form.get("account", "").strip()
    password = request.form.get("password", "").strip()

    if not account or not password:
        raise ApiError(
            "account and password are required",
            code=ErrorCode.ACCOUNT_OR_PASSWORD_REQUIRED,
        )

    u = User.get_or_none(User.uid == uid)
    if not u or not u.password_hash:
        raise ApiError(
            "no password has been set for this account", code=ErrorCode.PASSWORD_NOT_SET
        )
    if not check_password_hash(u.password_hash, password):
        raise ApiError("incorrect password", code=ErrorCode.INVALID_PASSWORD)

    try:
        ret = delete_account(uid=uid, account=account)
    except PassportError as e:
        raise ApiError(str(e), code=ErrorCode.PARAM_ERROR)
    else:
        rdb.delete(f"{PROC_NAME}:unbind_vcode:{account}")
        record_audit_log(
            uid=uid,
            action="unbind_account",
            detail={"account": account},
            ip=get_ip(),
            user_agent=request.headers.get("User-Agent", ""),
        )
        return new_res(success=True, data=dict(deleted=ret))


@bp.post("/user/delete")
@apilogin_required
def user_delete():
    """注销账号接口。

    有密码的本地账号需输入密码确认操作；第三方登录/未设置密码的账号
    （password_hash 为空）已通过登录态认证，凭登录态即可注销。
    检查用户名下无 OIDC 客户端后，级联删除所有用户数据
    （User / Auth / LoginRecord / OIDC 授权 / Passkey 等）。

    :form password: 有密码账号的当前密码（必填）
    :returns: 操作结果 JSON（成功时同时清除登录态 Cookie）
    """
    from flask import jsonify

    uid = g.user["uid"]

    u = User.get_or_none(User.uid == uid)
    if not u:
        raise ApiError("user not found", code=ErrorCode.PARAM_ERROR)

    # 第三方/未设置密码账号无密码可验，登录态（@apilogin_required）即认证依据
    if u.password_hash:
        password = request.form.get("password", "")
        if not password:
            raise ApiError(
                "password is required to confirm account deletion",
                code=ErrorCode.PASSWORD_REQUIRED,
            )
        if not check_password_hash(u.password_hash, password):
            raise ApiError("incorrect password", code=ErrorCode.INVALID_PASSWORD)

    # 检查是否有 OIDC 客户端
    if list_oauth_clients(uid):
        raise ApiError(
            "please delete all your OIDC clients before deleting the account",
            code=ErrorCode.OIDC_CLIENTS_EXIST,
        )

    try:
        ret = delete_user_data(
            uid=uid,
            ip=request.remote_addr or "",
            user_agent=request.user_agent.string or "",
        )
    except PassportError as e:
        raise ApiError(str(e), code=ErrorCode.PARAM_ERROR)
    else:
        resp = jsonify(new_res(success=True, data=dict(deleted=ret)))
        resp.set_cookie("sid", "", expires=0, httponly=True, samesite="Lax")
        return resp


@bp.post("/vcode_login")
@ip_rate_limit
def vcode_login():
    """验证码注册登录接口。

    校验用户提交的验证码，验证通过后设置登录态 Cookie，
    同时写入登录记录。

    :form account: 邮箱地址或手机号（必填）
    :form code: 验证码（必填）
    :form remember: 是否记住登录（可选，勾选后 Cookie 有效期 7 天，否则 2 小时）
    :form next: 登录后跳转地址（可选，用于识别 OIDC 客户端来源）
    :returns: 登录结果 JSON（服务端已设置 sid Cookie）
    """
    account = request.form.get("account", "").strip()
    code = request.form.get("code", "").strip()

    if not account or not code:
        raise ApiError(
            "account and verification code are required",
            code=ErrorCode.ACCOUNT_OR_VCODE_REQUIRED,
        )

    stored = rdb.get(f"{PROC_NAME}:login_vcode:{account}")
    if isinstance(stored, bytes):
        stored = stored.decode()
    if not stored:
        raise ApiError(
            "verification code has expired, please request a new one",
            code=ErrorCode.VCODE_EXPIRED,
        )
    if stored != code:
        raise ApiError("invalid verification code", code=ErrorCode.VCODE_INVALID)

    # 验证通过，删除已用验证码
    rdb.delete(f"{PROC_NAME}:login_vcode:{account}")

    expire = 604800 if request.form.get("remember") else 7200
    auth = get_auth(account)
    if not auth:
        # 验证码登录即注册：验证码证明账号归属，自动创建无密码账号
        register_vcode(account)
        auth = get_auth(account)
        if not auth:
            raise ApiError(
                "login failed, account is abnormal", code=ErrorCode.LOGIN_FAILED
            )
        record_audit_log(
            uid=auth["uid"],
            action="register",
            detail={"account": account, "method": "vcode"},
            ip=get_ip(),
            user_agent=request.headers.get("User-Agent", ""),
        )

    # 记录登录日志（异步，含 IP 地理位置、设备指纹）
    uid = auth["uid"]
    RecordLoginInterface(
        uid=uid,
        account=account,
        method="vcode",
        ip=get_ip(),
        ua=request.headers.get("User-Agent", ""),
        accept_lang=request.headers.get("Accept-Language", ""),
    )

    return auto_set_user_state(
        account,
        expire,
        new_res(success=True),
        method="vcode",
        source=resolve_login_source(request.form.get("next", "")),
    )


def passkey_required(f):
    """装饰器：Passkey 功能未开启时直接返回 功能未开启 错误。

    检查 ``PASSKEY_RP_ID`` 是否为有效值（localhost 或真实域名），
    否则抛出 ApiError 提示用户该功能不可用。
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        from ..basis.conf import config

        rp_id = (config.get("PASSKEY_RP_ID") or "").strip()
        if not is_passkey_enabled(rp_id):
            raise ApiError(
                "Passkey feature is disabled, please configure PASSKEY_RP_ID to a valid domain",
                code=ErrorCode.PASSKEY_DISABLED,
            )
        return f(*args, **kwargs)

    return decorated


@bp.post("/passkey/register/options")
@apilogin_required
@passkey_required
def passkey_register_options():
    """生成 Passkey 注册选项。

    用户已登录时调用，返回 ``PublicKeyCredentialCreationOptions`` JSON，
    浏览器需调用 ``navigator.credentials.create()`` 完成注册。

    :returns: 注册选项 JSON（含 challenge、rp、user 等字段）
    """
    uid = g.user["uid"]
    account = g.user["account"]
    try:
        options = PasskeyClient.generate_registration_options(
            uid=uid,
            account=account,
            display_name=account,
        )
    except PasskeyError as e:
        raise ApiError(str(e), code=ErrorCode.PASSKEY_ERROR)
    return new_res(success=True, data=options)


@bp.post("/passkey/register/verify")
@apilogin_required
@passkey_required
def passkey_register_verify():
    """验证 Passkey 注册结果。

    接收浏览器调用 ``navigator.credentials.create()`` 返回的
    ``PublicKeyCredential`` JSON，验证成功后存储公钥。

    :json: 浏览器返回的 PublicKeyCredential 对象
    :returns: 关联的 credential_id 和 device_name
    """
    uid = g.user["uid"]
    credential_json = request.get_json(silent=True)
    if not credential_json:
        raise ApiError(
            "credential data is required", code=ErrorCode.CREDENTIAL_REQUIRED
        )
    try:
        result = PasskeyClient.verify_registration_response(uid, credential_json)
    except PasskeyError as e:
        raise ApiError(str(e), code=ErrorCode.PASSKEY_ERROR)
    record_audit_log(
        uid=uid,
        action="passkey_add",
        detail={
            "device_name": result.get("device_name", ""),
            "credential_id": result.get("credential_id", ""),
        },
        ip=get_ip(),
        user_agent=request.headers.get("User-Agent", ""),
    )
    return new_res(success=True, data=result)


@bp.post("/passkey/login/options")
@passkey_required
def passkey_login_options():
    """生成 Passkey 登录认证选项。

    未登录状态可调用，浏览器需调用 ``navigator.credentials.get()``
    完成签名认证。支持有条件发现（conditional UI / autofill）。

    :returns: 认证选项 JSON（含 challenge、rpId 等字段）
    """
    uid = request.get_json(silent=True, cache=True) or {}
    uid = uid.get("uid", "") if isinstance(uid, dict) else ""
    try:
        options = PasskeyClient.generate_authentication_options(uid=uid)
    except PasskeyError as e:
        raise ApiError(str(e), code=ErrorCode.PASSKEY_ERROR)
    return new_res(success=True, data=options)


@bp.post("/passkey/login/verify")
@passkey_required
def passkey_login_verify():
    """验证 Passkey 登录认证结果。

    接收浏览器调用 ``navigator.credentials.get()`` 返回的
    ``PublicKeyCredential`` JSON，验证签名成功后返回 JWT token。

    :json: 浏览器返回的 PublicKeyCredential 对象
    :returns: JWT token（用于后续 API 鉴权）
    """
    credential_json = request.get_json(silent=True)
    if not credential_json:
        raise ApiError(
            "credential data is required", code=ErrorCode.CREDENTIAL_REQUIRED
        )
    try:
        result = PasskeyClient.verify_authentication_response(credential_json)
    except PasskeyError as e:
        raise ApiError(str(e), code=ErrorCode.PASSKEY_ERROR)

    uid = result["uid"]
    # 查找用户的本地账号（优先使用 username 类型账号）
    accounts = list_accounts(uid)
    account = ""
    for a in accounts:
        if a.get("type") == "username":
            account = a["account"]
            break
    if not account and accounts:
        account = accounts[0]["account"]
    if not account:
        raise ApiError(
            "passkey authentication succeeded but no account found",
            code=ErrorCode.ACCOUNT_NOT_FOUND,
        )

    # 会话保持时长支持用户在安全页自定义，未设置时使用默认值
    expire = get_login_session_expire(uid)
    ret = auto_set_user_state(
        account=account,
        expire=expire,
        data={
            "success": True,
            "data": {
                "uid": uid,
                "credential_id": result["credential_id"],
                "device_name": result["device_name"],
            },
        },
        method="passkey",
        source=resolve_login_source(credential_json.get("next", "")),
    )
    if not ret:
        raise ApiError("generate token failed", code=ErrorCode.TOKEN_GENERATE_FAILED)

    # 记录登录日志
    RecordLoginInterface(
        uid=uid,
        account=account,
        method="passkey",
        ip=get_ip(),
        ua=request.headers.get("User-Agent", ""),
        accept_lang=request.headers.get("Accept-Language", ""),
    )

    return ret


@bp.get("/passkey/credentials")
@apilogin_required
@passkey_required
def passkey_list_credentials():
    """列出当前用户绑定的所有 Passkey 凭证。

    :returns: data 中包含 credentials 列表
    """
    uid = g.user["uid"]
    credentials = PasskeyClient.list_credentials(uid)
    return new_res(success=True, data=dict(credentials=credentials))


@bp.delete("/passkey/credential/<credential_id>")
@apilogin_required
@passkey_required
def passkey_delete_credential(credential_id: str):
    """删除指定 Passkey 凭证。

    :param credential_id: 凭证 ID（base64url 编码）
    :returns: 删除结果
    """
    uid = g.user["uid"]
    ret = PasskeyClient.delete_credential(uid, credential_id)
    if not ret:
        raise ApiError("credential not found")
    record_audit_log(
        uid=uid,
        action="passkey_delete",
        detail={"credential_id": credential_id},
        ip=get_ip(),
        user_agent=request.headers.get("User-Agent", ""),
    )
    return new_res(success=True, data=dict(deleted=True))


@bp.put("/passkey/credential/<credential_id>")
@apilogin_required
@passkey_required
def passkey_rename_credential(credential_id: str):
    """重命名指定 Passkey 凭证的设备名称。

    :param credential_id: 凭证 ID（base64url 编码）
    :returns: 重命名结果
    """
    uid = g.user["uid"]
    device_name = request.form.get("device_name", "").strip()
    if not device_name:
        raise ApiError("device_name is required")
    if len(device_name) > 128:
        raise ApiError("device_name too long (max 128)")
    ret = PasskeyClient.rename_credential(uid, credential_id, device_name)
    if not ret:
        raise ApiError("credential not found")
    return new_res(success=True, data=dict(renamed=True))


@bp.get("/notice")
def notice():
    """获取公告通知列表，无需登录。

    返回未过期的公告（etime=0 表示永不过期）。
    """
    return new_res(success=True, data=NoticeClient.get_notices())


# Geetest 验证初始化接口，GET请求
@bp.route("/geetest/register", methods=["GET"])
def geetest_register():
    # 必传参数
    #     digestmod 此版本sdk可支持md5、sha256、hmac-sha256，md5之外的算法需特殊配置的账号，联系极验客服
    # 自定义参数,可选择添加
    #     client_type 客户端类型，web：电脑上的浏览器；h5：手机上的浏览器，包括移动应用内完全内置的web_view；native：通过原生sdk植入app应用的方式；unknown：未知
    #     ip_address 客户端请求sdk服务器的ip地址
    bypass_status = get_bypass_cache()
    gt_lib = GeetestLib(
        config.get("GEETEST_CAPTCHA_ID"), config.get("GEETEST_CAPTCHA_KEY")
    )
    digestmod = "md5"
    param_dict = {"digestmod": digestmod, "client_type": "web", "ip_address": get_ip()}
    if bypass_status == "success":
        result = gt_lib.register(digestmod, param_dict)
    else:
        result = gt_lib.local_init()
    # 注意，不要更改返回的结构和值类型
    return Response(result.data, content_type="application/json;charset=UTF-8")


# Geetest 二次验证接口，POST请求
@bp.route("/geetest/validate", methods=["POST"])
def geetest_validate():
    challenge = request.form.get(GeetestLib.GEETEST_CHALLENGE, None)
    validate = request.form.get(GeetestLib.GEETEST_VALIDATE, None)
    seccode = request.form.get(GeetestLib.GEETEST_SECCODE, None)
    bypass_status = get_bypass_cache()
    gt_lib = GeetestLib(
        config.get("GEETEST_CAPTCHA_ID"), config.get("GEETEST_CAPTCHA_KEY")
    )
    if bypass_status == "success":
        result = gt_lib.successValidate(challenge, validate, seccode)
    else:
        result = gt_lib.failValidate(challenge, validate, seccode)
    # 注意，不要更改返回的结构和值类型
    if result.status == 1:
        response = {"result": "success", "version": GeetestLib.VERSION}
    else:
        response = {"result": "fail", "version": GeetestLib.VERSION, "msg": result.msg}
    return response


# ---------------------------------------------------------------------------
# 后台管理接口（仅 admin / superadmin）
# ---------------------------------------------------------------------------

def _record_admin_audit(
    action: str, target_uid: str, detail: dict
) -> None:
    """记录一次后台写操作的审计日志（操作者与被操作用户各记一条）。

    操作者视角：``uid`` 为操作者，detail 内含 ``target_uid``（被操作对象）；
    被操作用户视角：``uid`` 为被操作用户，detail 内含 ``operator_uid``，
    便于用户在「安全」页知晓自己的账号/应用被哪位管理员改动。

    :param action: 操作类型，如 ``admin_role_set``
    :param target_uid: 被操作用户 uid（无对应用户时传空串则只记操作者）
    :param detail: 操作详情（两类视角共用的业务字段）
    """
    ip = get_ip()
    ua = request.headers.get("User-Agent", "")
    record_audit_log(
        uid=g.user["uid"],
        action=action,
        detail=dict(detail, target_uid=target_uid),
        ip=ip,
        user_agent=ua,
    )
    if target_uid and target_uid != g.user["uid"]:
        record_audit_log(
            uid=target_uid,
            action=action,
            detail=dict(detail, operator_uid=g.user["uid"]),
            ip=ip,
            user_agent=ua,
        )


def _parse_page_args(default_per_page: int = 10) -> tuple:
    """解析分页参数 ``page`` / ``per_page``，非法值回退默认。

    :param default_per_page: 每页默认条数
    :returns: (page, per_page) 元组，page 最小 1，per_page 限制 [1, 100]
    """
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get("per_page", default_per_page))
    except (TypeError, ValueError):
        per_page = default_per_page
    return max(1, page), max(1, min(per_page, 100))


def _parse_ts_arg(name: str):
    """解析 Unix 时间戳查询参数，缺失或非法时返回 None。"""
    value = request.args.get(name, "")
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _admin_user_filters() -> dict:
    """收集后台用户列表的筛选与排序参数。"""
    status_raw = request.args.get("status", "")
    return dict(
        keyword=request.args.get("keyword", "").strip(),
        status=int(status_raw) if status_raw in ("0", "1") else None,
        role=request.args.get("role", "").strip(),
        login_type=request.args.get("login_type", "").strip(),
        start=_parse_ts_arg("start"),
        end=_parse_ts_arg("end"),
        order=request.args.get("order", "ctime").strip(),
    )


@bp.get("/admin/users")
@api_admin_required
def admin_users():
    """后台：分页查询用户列表（支持搜索、筛选与排序）。

    :query keyword: 搜索关键词（uid / 昵称 / 账号）
    :query status: 状态筛选，0 禁用 / 1 启用
    :query role: 平台角色筛选（superadmin / admin / user）
    :query login_type: 登录方式筛选：password / third / passkey
    :query start: 注册时间下界（Unix 时间戳）
    :query end: 注册时间上界（Unix 时间戳）
    :query order: 排序方式：ctime（默认）或 last_login
    :query page: 页码，默认 1
    :query per_page: 每页条数，默认 10
    :returns: data 中包含 users、total、page、per_page、pages
    """
    page, per_page = _parse_page_args()
    users, total = admin_list_users(
        page=page, per_page=per_page, **_admin_user_filters()
    )
    pages = (total + per_page - 1) // per_page if per_page else 0
    return new_res(
        success=True,
        data=dict(
            users=users,
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
        ),
    )


@bp.get("/admin/user/detail")
@api_admin_required
def admin_user_detail_api():
    """后台：查看单个用户的聚合详情。

    :query uid: 目标用户 uid（必填）
    :returns: data 为包含资料、账号、会话、登录与审计的详情字典
    """
    uid = request.args.get("uid", "").strip()
    if not uid:
        raise ApiError("uid is required", code=ErrorCode.PARAM_ERROR)
    detail = admin_user_detail(uid)
    if not detail:
        raise ApiError("user not found", code=ErrorCode.USER_NOT_FOUND)
    return new_res(success=True, data=detail)


@bp.get("/admin/users/export")
@api_superadmin_required
def admin_users_export():
    """后台：按当前筛选条件导出用户 CSV（仅 superadmin）。

    :returns: text/csv 附件
    """
    filters = _admin_user_filters()
    filters.pop("order", None)
    rows = []
    page = 1
    while len(rows) < 5000:
        users, total = admin_list_users(
            page=page, per_page=100, **filters
        )
        if not users:
            break
        rows.extend(users)
        if len(rows) >= total:
            break
        page += 1

    buf = StringIO()
    # BOM 便于 Excel 正确识别 UTF-8
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(
        [
            "uid",
            "昵称",
            "绑定账号",
            "性别",
            "地区",
            "平台角色",
            "状态",
            "注册时间",
            "最后登录",
        ]
    )
    gender_map = {0: "女", 1: "男"}
    for u in rows:
        accounts = "; ".join(a.get("account", "") for a in u["accounts"])
        ctime = strftime("%Y-%m-%d %H:%M:%S", localtime(u["ctime"]))
        last = (
            strftime("%Y-%m-%d %H:%M:%S", localtime(u["last_login"]))
            if u.get("last_login")
            else ""
        )
        writer.writerow(
            [
                u["uid"],
                u.get("nickname", ""),
                accounts,
                gender_map.get(u.get("gender"), "未知"),
                u.get("location", ""),
                u.get("role", ""),
                "禁用" if u.get("status") == 0 else "正常",
                ctime,
                last,
            ]
        )
    filename = "users-{}.csv".format(strftime("%Y%m%d-%H%M%S"))
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="{}"'.format(filename)
        },
    )


@bp.get("/admin/audit_logs")
@api_admin_required
def admin_audit_logs():
    """后台：分页查询全部审计日志。

    :query keyword: 关键词（uid 或 detail 内容）
    :query action: 操作类型前缀（如 admin）
    :query start: 时间下界（Unix 时间戳）
    :query end: 时间上界（Unix 时间戳）
    :query page: 页码，默认 1
    :query per_page: 每页条数，默认 10
    :returns: data 中包含 logs、total、page、per_page、pages
    """
    page, per_page = _parse_page_args()
    logs, total = admin_list_audit_logs(
        keyword=request.args.get("keyword", "").strip(),
        action=request.args.get("action", "").strip(),
        start=_parse_ts_arg("start"),
        end=_parse_ts_arg("end"),
        page=page,
        per_page=per_page,
    )
    pages = (total + per_page - 1) // per_page if per_page else 0
    return new_res(
        success=True,
        data=dict(
            logs=logs,
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
        ),
    )


@bp.get("/admin/login_records")
@api_admin_required
def admin_login_records():
    """后台：分页查询用户登录记录。

    :query keyword: 关键词（账号 / uid / 昵称）
    :query method: 登录方式精确匹配
    :query ip: IP 模糊匹配
    :query start: 时间下界（Unix 时间戳）
    :query end: 时间上界（Unix 时间戳）
    :query page: 页码，默认 1
    :query per_page: 每页条数，默认 10
    :returns: data 中包含 records、total、page、per_page、pages
    """
    page, per_page = _parse_page_args()
    records, total = admin_list_login_records(
        keyword=request.args.get("keyword", "").strip(),
        method=request.args.get("method", "").strip(),
        ip=request.args.get("ip", "").strip(),
        start=_parse_ts_arg("start"),
        end=_parse_ts_arg("end"),
        page=page,
        per_page=per_page,
    )
    pages = (total + per_page - 1) // per_page if per_page else 0
    return new_res(
        success=True,
        data=dict(
            records=records,
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
        ),
    )


@bp.put("/admin/user/role")
@api_superadmin_required
def admin_set_user_role():
    """后台：设置指定用户的内置平台角色（保留客户端角色，仅 superadmin）。

    :form uid: 目标用户 uid（必填）
    :form roles: 平台角色，空格分隔（superadmin / admin / user）
    :returns: data 中包含更新后的 uid 与 role
    """
    uid = request.form.get("uid", "").strip()
    roles = [
        r.strip().lower()
        for r in request.form.get("roles", "").split()
        if r.strip()
    ]
    if not uid:
        raise ApiError("uid is required", code=ErrorCode.PARAM_ERROR)
    for role in roles:
        if role not in ("superadmin", "admin", "user"):
            raise ApiError("invalid role", code=ErrorCode.ROLE_INVALID)
    if not has_uid(uid):
        raise ApiError("user not found", code=ErrorCode.USER_NOT_FOUND)

    # 防止移除最后一个 superadmin 导致后台失联
    profile = get_user_by_uid(uid) or {}
    # 归一化大小写，兼容历史数据中的 SuperAdmin 等形式
    current_roles = {
        normalize_builtin_role(r) for r in (profile.get("role") or "").split()
    }
    if (
        "superadmin" not in roles
        and "superadmin" in current_roles
        and count_superadmins() <= 1
    ):
        raise ApiError(
            "cannot remove the last superadmin",
            code=ErrorCode.LAST_SUPERADMIN,
        )

    try:
        new_role = set_platform_roles(uid, roles)
    except PassportError as e:
        raise ApiError(str(e), code=ErrorCode.ROLE_INVALID)
    _record_admin_audit("admin_role_set", uid, {"roles": new_role})
    return new_res(success=True, data=dict(uid=uid, role=new_role))


@bp.put("/admin/user/status")
@api_admin_required
def admin_set_user_status():
    """后台：启用或禁用指定用户（禁止禁用自己）。

    :form uid: 目标用户 uid（必填）
    :form status: 状态，1=启用，0=禁用
    :returns: data 中包含 uid 与 status
    """
    uid = request.form.get("uid", "").strip()
    status = request.form.get("status", "")
    if status not in ("0", "1"):
        raise ApiError("status must be 0 or 1", code=ErrorCode.PARAM_ERROR)
    if not has_uid(uid):
        raise ApiError("user not found", code=ErrorCode.USER_NOT_FOUND)
    if uid == g.user["uid"] and status == "0":
        raise ApiError("cannot disable yourself", code=ErrorCode.PARAM_ERROR)
    try:
        update_profile(uid, status=int(status))
    except PassportError as e:
        raise ApiError(str(e), code=ErrorCode.PARAM_ERROR)
    _record_admin_audit("admin_user_status", uid, {"status": int(status)})
    return new_res(success=True, data=dict(uid=uid, status=int(status)))


@bp.get("/admin/oidc/clients")
@api_admin_required
def admin_oidc_clients():
    """后台：分页查询所有 OIDC 客户端（含所有者与内部应用标记）。

    :query keyword: 搜索关键词，匹配应用名称或所有者（可选）
    :query is_internal: 内部应用筛选，1 / 0（可选）
    :query has_role: 为 1 时仅返回授权范围含 role 的客户端
    :query page: 页码，默认 1
    :query per_page: 每页条数，默认 10
    :returns: data 中包含 clients、total、page、per_page、pages
    """
    keyword = request.args.get("keyword", "").strip()
    page, per_page = _parse_page_args()
    internal_raw = request.args.get("is_internal", "")
    is_internal = None
    if internal_raw in ("0", "1"):
        is_internal = internal_raw == "1"
    clients, total = list_oauth_clients_page(
        keyword=keyword,
        page=page,
        per_page=per_page,
        is_internal=is_internal,
        has_role=request.args.get("has_role") == "1",
    )
    pages = (total + per_page - 1) // per_page if per_page else 0
    return new_res(
        success=True,
        data=dict(
            clients=clients,
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
        ),
    )


@bp.put("/admin/oidc/client/internal")
@api_superadmin_required
def admin_set_oidc_client_internal():
    """后台：标记 OIDC 应用是否为内部应用（仅 superadmin）。

    内部应用在申请 ``role`` scope 时可获得用户平台角色，等效于配置项
    ``OIDC_INTERNAL_CLIENTS``。

    :form client_id: 客户端 ID（必填）
    :form is_internal: 是否内部应用，1/0（必填）
    :returns: data 为更新后的客户端信息
    """
    client_id = request.form.get("client_id", "").strip()
    if not client_id:
        raise ApiError(
            "client_id is required", code=ErrorCode.CLIENT_ID_REQUIRED
        )
    is_internal_raw = request.form.get("is_internal", "")
    if is_internal_raw not in ("0", "1"):
        raise ApiError(
            "is_internal must be 0 or 1", code=ErrorCode.PARAM_ERROR
        )
    is_internal = is_internal_raw == "1"
    try:
        ret = admin_set_client_internal(client_id, is_internal)
    except PermissionError:
        raise ApiError("client not found", code=ErrorCode.CLIENT_NOT_FOUND)
    except PassportError as e:
        raise ApiError(str(e), code=ErrorCode.PARAM_ERROR)
    _record_admin_audit(
        "admin_client_internal",
        str(ret.get("uid") or ""),
        {
            "client_id": client_id,
            "name": ret.get("name", ""),
            "is_internal": is_internal,
        },
    )
    return new_res(success=True, data=ret)


@bp.get("/admin/oidc/client/detail")
@api_admin_required
def admin_oidc_client_detail():
    """后台：查看 OIDC 客户端只读详情（后台不提供编辑）。

    :query client_id: 客户端 ID（必填）
    :returns: data 为客户端详情（含所有者、回调地址、授权与令牌数）
    """
    client_id = request.args.get("client_id", "").strip()
    if not client_id:
        raise ApiError(
            "client_id is required", code=ErrorCode.CLIENT_ID_REQUIRED
        )
    detail = admin_get_oauth_client(client_id)
    if not detail:
        raise ApiError("client not found", code=ErrorCode.CLIENT_NOT_FOUND)
    return new_res(success=True, data=detail)


@bp.delete("/admin/oidc/client/<client_id>")
@api_superadmin_required
def admin_delete_oidc_client(client_id: str):
    """后台：删除任意 OIDC 客户端（仅 superadmin）。

    同时清理该客户端的令牌与授权记录，并写入双方审计日志。

    :param client_id: 客户端 ID
    :returns: data 中包含 deleted
    """
    detail = admin_get_oauth_client(client_id)
    if not detail:
        raise ApiError("client not found", code=ErrorCode.CLIENT_NOT_FOUND)
    try:
        ret = admin_delete_oauth_client(client_id)
    except PermissionError:
        raise ApiError("client not found", code=ErrorCode.CLIENT_NOT_FOUND)
    except PassportError as e:
        raise ApiError(str(e), code=ErrorCode.PARAM_ERROR)
    _record_admin_audit(
        "admin_client_delete",
        str(detail.get("uid") or ""),
        {"client_id": client_id, "name": detail.get("name", "")},
    )
    return new_res(success=True, data=dict(deleted=ret))
