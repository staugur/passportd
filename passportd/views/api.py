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

from flask import Blueprint, request, abort, g
from werkzeug.security import check_password_hash

from ..libs.interface import (
    RecordLoginInterface,
    RegisterInterface,
    UploadInterface,
    VCodeInterface,
)
from ..models.user import (
    add_account,
    change_password,
    delete_account,
    generate_jwt,
    get_account as get_auth,
    has_account,
    list_accounts,
    list_login_records,
)
from ..models.oidc import (
    count_oauth_authorizations,
    create_oauth_client,
    delete_oauth_client,
    delete_oauth_authorization,
    list_oauth_clients,
    list_oauth_authorizations_by_user,
    update_oauth_client,
)
from ..models.model import User
from ..basis.errors import ApiError, PassportError
from ..basis.vars import JWE_HEADER, PROC_NAME
from ..basis.common import new_res
from ..utils.web import apilogin_required, check_sms_rate_limit, get_ip
from ..utils.common import (
    generate_digital_verification_code,
    parse_account_classify,
    parse_encrypted_password,
    rdb,
    read_rsa_public_key,
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
        raise ApiError(str(e))
    else:
        return new_res(
            success=True,
            data=dict(header=JWE_HEADER, key=key),  # type: ignore
        )


@bp.post("/user/signup")
def signup():
    """API 用户注册接口（仅返回 JSON）。

    用户名注册：account + password 即可。
    邮箱/手机号注册：account + password + vcode（需先通过 send_signup_vcode 获取验证码）。

    :form account: 用户账号（必填）
    :form password: 密码（必填，明文或 RSA 加密）
    :form repassword: 确认密码
    :form encrypted_password: 加密后的密码（JWE 格式，优先使用）
    :form encrypted_repassword: 加密后的确认密码
    :form vcode: 验证码（邮箱/手机号注册时必填）
    :form nickname: 昵称
    :form bio: 个人简介
    :form gender: 性别
    :form avatar: 头像 URL
    :form location: 地区
    :returns: 注册结果 JSON
    """
    # post signup for http api response only.
    #: account, password(encrypted) is required, other fields as profile
    data = request.form.to_dict()
    account = data.get("account", "")
    password = data.get("password", "")
    repassword = data.get("repassword", "")
    decrypted_password = (
        parse_encrypted_password(data.get("encrypted_password", "")) or password
    )
    decrypted_repassword = (
        parse_encrypted_password(data.get("encrypted_repassword", "")) or repassword
    )
    vcode = data.get("vcode", "").strip()
    nickname = data.get("nickname", "")
    bio = data.get("bio", "")
    gender = data.get("gender", 2)
    avatar = data.get("avatar", "")
    location = data.get("location", "Unknown")

    if not account or not decrypted_password:
        raise ApiError("account and password is required")
    if decrypted_password != decrypted_repassword:
        raise ApiError("password and repassword not match")

    # 邮箱/手机号注册需要验证码
    classify = parse_account_classify(account)
    if classify in ("email", "mobile"):
        if not vcode:
            raise ApiError("验证码不能为空")
        stored = rdb.get(f"{PROC_NAME}:signup_vcode:{account}")
        if isinstance(stored, bytes):
            stored = stored.decode()
        if not stored:
            raise ApiError("验证码已过期，请重新获取")
        if stored != vcode:
            raise ApiError("验证码错误")
        # 验证通过，删除已用验证码
        rdb.delete(f"{PROC_NAME}:signup_vcode:{account}")

    return RegisterInterface(
        account,
        decrypted_password,
        nickname=nickname,
        bio=bio,
        gender=gender,
        avatar=avatar,
        location=location,
    )


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
        raise ApiError("new_password is required")
    if new_pwd != repassword:
        raise ApiError("new_password and repassword do not match")
    if len(new_pwd) < 6:
        raise ApiError("new_password must be at least 6 characters")

    try:
        ret = change_password(uid, account, new_pwd)
    except PassportError as e:
        raise ApiError(str(e))
    else:
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
            raise ApiError("client_id is required")
        try:
            ret = delete_oauth_client(uid=uid, client_id=client_id)
        except PassportError as e:
            raise ApiError(str(e))
        else:
            return new_res(success=True, data=dict(deleted=ret))

    if request.method == "PUT":
        client_id = request.form.get("client_id", "")
        if not client_id:
            raise ApiError("client_id is required")
        name = request.form.get("name", "")
        bio = request.form.get("bio", "")
        homepage = request.form.get("homepage", "")
        redirect_uri = request.form.get("redirect_uri", "")
        scope = request.form.get("scope", "")
        try:
            ret = update_oauth_client(
                uid=uid,
                client_id=client_id,
                name=name,
                bio=bio,
                homepage=homepage,
                redirect_uri=redirect_uri,
                scope=scope,
            )
        except PassportError as e:
            raise ApiError(str(e))
        else:
            return new_res(success=True, data=ret)

    # POST: create
    name = request.form.get("name", "")
    bio = request.form.get("bio", "")
    homepage = request.form.get("homepage", "")
    redirect_uri = request.form.get("redirect_uri", "")
    scope = request.form.get("scope", "")
    try:
        ret = create_oauth_client(
            uid=uid,
            name=name,
            bio=bio,
            homepage=homepage,
            redirect_uri=redirect_uri,
            scope=scope,
        )
    except PassportError as e:
        raise ApiError(str(e))
    else:
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
        raise ApiError("client_id is required")
    try:
        ret = delete_oauth_authorization(uid=uid, client_id=client_id)
    except PassportError as e:
        raise ApiError(str(e))
    else:
        return new_res(success=True, data=dict(deleted=ret))


@bp.post("/send_signup_vcode")
def send_signup_vcode():
    """发送注册验证码（邮箱或短信）。

    根据账号格式自动判断为邮箱或手机号，通过对应渠道发送 6 位数字验证码。
    该账号必须未被注册，同一账号 60 秒内不可重复请求，验证码 5 分钟内有效。

    :form account: 邮箱地址或手机号（必填）
    :returns: 发送结果 JSON
    """
    account = request.form.get("account", "").strip()
    if not account:
        raise ApiError("账号不能为空")

    classify = parse_account_classify(account)
    if classify not in ("email", "mobile"):
        raise ApiError("请输入有效的邮箱或手机号")

    if has_account(account):
        raise ApiError("该账号已注册，请直接登录")

    check_sms_rate_limit(account)

    # 60s 内同一账号不可重复发送
    rl_key = f"{PROC_NAME}:signup_vcode_rl:{account}"
    if rdb.exists(rl_key):
        raise ApiError("操作过于频繁，请 60 秒后重试")

    code = generate_digital_verification_code()
    vi = VCodeInterface()

    if classify == "email":
        ret = vi.send_email(account, code)
    else:
        ret = vi.send_sms(account, code)

    if ret["success"] is True:
        # 验证码写入 Redis，5 分钟有效
        rdb.setex(f"{PROC_NAME}:signup_vcode:{account}", 300, code)
        rdb.setex(rl_key, 60, "1")

    return ret


@bp.post("/send_login_vcode")
def send_login_vcode():
    """发送登录验证码（邮箱或短信）。

    根据账号格式自动判断为邮箱或手机号，通过对应渠道发送 6 位数字验证码。
    同一账号 60 秒内不可重复请求，验证码 5 分钟内有效。

    :form account: 邮箱地址或手机号（必填）
    :returns: 发送结果 JSON
    """
    account = request.form.get("account", "").strip()
    if not account:
        raise ApiError("账号不能为空")

    classify = parse_account_classify(account)
    if classify not in ("email", "mobile"):
        raise ApiError("请输入有效的邮箱或手机号")

    if not has_account(account):
        raise ApiError("该账号不存在，请先注册")

    check_sms_rate_limit(account)

    # 60s 内同一账号不可重复发送
    rl_key = f"{PROC_NAME}:login_vcode_rl:{account}"
    if rdb.exists(rl_key):
        raise ApiError("操作过于频繁，请 60 秒后重试")

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
        raise ApiError("账号不能为空")

    classify = parse_account_classify(account)
    if classify not in ("email", "mobile"):
        raise ApiError("请输入有效的邮箱或手机号")

    if has_account(account):
        raise ApiError("该账号已被绑定，请使用其他账号")

    check_sms_rate_limit(account)

    rl_key = f"{PROC_NAME}:bind_vcode_rl:{account}"
    if rdb.exists(rl_key):
        raise ApiError("操作过于频繁，请 60 秒后重试")

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
        raise ApiError("账号和验证码不能为空")

    classify = parse_account_classify(account)
    if classify not in ("email", "mobile"):
        raise ApiError("仅支持绑定邮箱或手机号")

    if has_account(account):
        raise ApiError("该账号已被绑定，请使用其他账号")

    stored = rdb.get(f"{PROC_NAME}:bind_vcode:{account}")
    if isinstance(stored, bytes):
        stored = stored.decode()
    if not stored or stored != code:
        raise ApiError("验证码错误或已过期")

    try:
        add_account(uid=uid, account=account)
    except PassportError as e:
        raise ApiError(str(e))
    else:
        rdb.delete(f"{PROC_NAME}:bind_vcode:{account}")
        return new_res(success=True, data=dict(account=account))


@bp.post("/user/unbind_account")
@apilogin_required
def user_unbind_account():
    """解绑邮箱或手机号接口。

    验证当前密码，通过后删除该 Auth 记录。

    :form account: 邮箱地址或手机号（必填）
    :form password: 当前密码（必填）
    :returns: 解绑结果 JSON
    """
    uid = g.user["uid"]
    account = request.form.get("account", "").strip()
    password = request.form.get("password", "").strip()

    if not account or not password:
        raise ApiError("账号和密码不能为空")

    u = User.get_or_none(User.uid == uid)
    if not u or not u.password_hash:
        raise ApiError("当前账号未设置密码")
    if not check_password_hash(u.password_hash, password):
        raise ApiError("密码错误")

    try:
        ret = delete_account(uid=uid, account=account)
    except PassportError as e:
        raise ApiError(str(e))
    else:
        rdb.delete(f"{PROC_NAME}:unbind_vcode:{account}")
        return new_res(success=True, data=dict(deleted=ret))


@bp.post("/vcode_login")
def vcode_login():
    """验证码登录接口。

    校验用户提交的验证码，验证通过后生成 JWT token 返回，
    同时写入登录记录。

    :form account: 邮箱地址或手机号（必填）
    :form code: 验证码（必填）
    :returns: 登录结果及 JWT token JSON
    """
    account = request.form.get("account", "").strip()
    code = request.form.get("code", "").strip()

    if not account or not code:
        raise ApiError("账号和验证码不能为空")

    stored = rdb.get(f"{PROC_NAME}:login_vcode:{account}")
    if isinstance(stored, bytes):
        stored = stored.decode()
    if not stored:
        raise ApiError("验证码已过期，请重新获取")
    if stored != code:
        raise ApiError("验证码错误")

    # 验证通过，删除已用验证码
    rdb.delete(f"{PROC_NAME}:login_vcode:{account}")

    expire = 7200
    auth = get_auth(account)
    if not auth:
        raise ApiError("登录失败，账号异常")

    token = generate_jwt(account, expire)
    if not token:
        raise ApiError("登录失败，账号异常")

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

    return new_res(success=True, data=dict(token=token))
