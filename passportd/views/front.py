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

import json
from urllib.parse import urlencode

from flask import (
    Blueprint,
    send_from_directory,
    current_app,
    request,
    url_for,
    render_template,
    redirect,
    g,
)

from ..models.user import (
    login,
    add_account,
    add_profile,
    get_account,
    list_accounts,
    list_login_records,
    update_profile,
    get_user_by_uid,
)
from ..libs.interface import (
    LoginInterface,
    RegisterInterface,
    RecordLoginInterface,
)
from ..basis.errors import ApiError, PassportError
from ..basis.vars import PROC_NAME
from ..utils.common import (
    rdb,
    parse_account_classify,
    parse_encrypted_password,
    rsa_encrypt,
)
from ..utils.web import (
    login_required,
    anonymous_required,
    clear_user_state,
    get_ip,
    get_redirect_url,
    auto_set_user_state,
    list_oauth2_providers,
)

bp = Blueprint("front", "front")


@bp.get("/")
def index():
    """首页：已登录跳转个人主页，未登录跳转登录页面。"""
    if g.signin:
        return redirect(url_for(".profile"))
    return redirect(url_for(".signin"))


@bp.get("/ping")
def ping():
    return "pong"


@bp.route("/uploads/<filename>")
@login_required
def uploaded(filename):
    """提供本地已上传文件的访问。

    :param filename: 文件名
    :returns: 文件响应
    """
    return send_from_directory(current_app.config["LOCAL_UPLOAD_FOLDER"], filename)


@bp.route("/user/signup", methods=["GET", "POST"])
@anonymous_required
def signup():
    """用户注册页面：GET 渲染注册表单，POST 处理注册。

    用户名注册：account + password 即可。
    邮箱/手机号注册：account + password + vcode（需先获取验证码）。
    """
    if request.method == "POST":
        account = request.form.get("account", "").strip()
        password = request.form.get("password", "").strip()
        repassword = request.form.get("repassword", "").strip()
        vcode = request.form.get("vcode", "").strip()
        nickname = request.form.get("nickname", "").strip()

        if not account or not password:
            return render_template(
                "signup.j2",
                error="账号和密码不能为空",
                account=account,
                nickname=nickname,
            )
        if password != repassword:
            return render_template(
                "signup.j2",
                error="两次密码输入不一致",
                account=account,
                nickname=nickname,
            )

        # 邮箱/手机号注册需要验证码
        classify = parse_account_classify(account)
        if classify in ("email", "mobile"):
            if not vcode:
                return render_template(
                    "signup.j2",
                    error="邮箱/手机号注册需要验证码",
                    account=account,
                    nickname=nickname,
                )
            stored = rdb.get(f"{PROC_NAME}:signup_vcode:{account}")
            if not stored:
                return render_template(
                    "signup.j2",
                    error="验证码已过期，请重新获取",
                    account=account,
                    nickname=nickname,
                )
            if stored != vcode:
                return render_template(
                    "signup.j2",
                    error="验证码错误",
                    account=account,
                    nickname=nickname,
                )
            # 验证通过，删除已用验证码
            rdb.delete(f"{PROC_NAME}:signup_vcode:{account}")

        res = RegisterInterface(account, password, nickname=nickname)
        if res["success"]:
            return redirect(
                url_for(".signin")
                + "?"
                + urlencode({"msg": "注册成功，请登录", "msg_type": "success"})
            )
        else:
            return render_template(
                "signup.j2",
                error=res.get("message", "注册失败"),
                account=account,
                nickname=nickname,
            )

    return render_template("signup.j2")


@bp.route("/user/signin", methods=["GET", "POST"])
@anonymous_required
def signin():
    """登录唯一入口：本地登录、OIDC登录。"""
    next = request.args.get("next", request.form.get("next", ""))

    # 构建 OAuth2 提供商列表（GET 和 POST 错误时都需要）
    oidc_state = (
        rsa_encrypt(next)
        if (next and url_for("root.oidc.authorize", _external=True) in next)
        else ""
    )
    oauth2_providers = list_oauth2_providers(oidc_state)

    if request.method == "POST":
        account = request.form.get("account", "")
        expire = 7200
        if request.form.get("remember"):
            expire = 604800  # 7 天
        decrypted_password = parse_encrypted_password(
            request.form.get("encrypted_password", "")
        )
        password = (
            decrypted_password
            if decrypted_password
            else request.form.get("password", "")
        )
        res = LoginInterface(account, password)
        if res["success"] is True:
            auth = get_account(account)
            if auth:
                RecordLoginInterface(
                    uid=auth["uid"],
                    account=account,
                    method="local",
                    ip=get_ip(),
                    ua=request.headers.get("User-Agent", ""),
                    accept_lang=request.headers.get("Accept-Language", ""),
                )
            return auto_set_user_state(account, expire, get_redirect_url())
        else:
            return render_template(
                "signin.j2",
                url=url_for(".signin", next=next),
                next=next,
                oauth2_providers=oauth2_providers,
                account=account,
                error=res.get("message", "登录失败"),
            )
    else:
        msg = request.args.get("msg", "")
        msg_type = request.args.get("msg_type", "")
        return render_template(
            "signin.j2",
            url=url_for(".signin", next=next),
            next=next,
            oauth2_providers=oauth2_providers,
            msg=msg,
            msg_type=msg_type,
        )


@bp.get("/user/signout")
@login_required
def signout():
    """退出登录：清除 session Cookie 并重定向。"""
    return clear_user_state()


@bp.route("/user/oauth2go", methods=["GET", "POST"])
@anonymous_required
def oauth2go():
    """OAuth2 首次登录选择页面。

    GET 展示页面让用户选择绑定已有账号或创建新账号。
    POST 处理绑定/创建操作，成功后自动签发登录态。

    :query key: Redis 中存储的 oauth2 数据键
    """
    key = request.args.get("key") or request.form.get("key", "")
    if not key:
        return "missing key", 400

    raw_data = rdb.get(key)
    if not raw_data:
        return "oauth2 data expired or invalid, please login with oauth2 again", 400

    oauth2_data = json.loads(raw_data)
    provider = oauth2_data["provider"]
    access_token = oauth2_data["access_token"]
    userinfo = oauth2_data["userinfo"]

    # 恢复登录后跳转地址（由 OIDC 授权流程通过 Redis 传入）
    target_next = (
        oauth2_data.get("next_url")
        or request.args.get("next")
        or request.form.get("next")
    )

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "bind":
            # 绑定已有本地账号
            local_account = request.form.get("local_account", "").strip()
            local_password = request.form.get("local_password", "").strip()
            if not local_account or not local_password:
                raise ApiError("请输入本地账号和密码")

            # 验证本地账号密码
            try:
                if not login(local_account, local_password):
                    raise ApiError("账号或密码错误")
            except PassportError as e:
                raise ApiError(str(e))

            # 获取本地账号的 uid
            local_auth = get_account(local_account)
            if not local_auth:
                raise ApiError("本地账号不存在")
            uid: str = local_auth["uid"]  # type: ignore

            # 绑定 OAuth 账号到已有用户
            try:
                add_account(
                    uid=uid,
                    account=userinfo["account"],
                    tpid=userinfo.get("tpid", ""),
                )
            except PassportError as e:
                raise ApiError(f"绑定失败: {e}")

            # 清除 Redis 并生成登录态
            rdb.delete(key)
            try:
                RecordLoginInterface(
                    uid=uid,
                    account=userinfo["account"],
                    method=f"oauth2_{provider}",
                    ip=get_ip(),
                    ua=request.headers.get("User-Agent", ""),
                    accept_lang=request.headers.get("Accept-Language", ""),
                )
                return auto_set_user_state(
                    userinfo["account"],
                    7200,
                    dict(
                        success=True,
                        msg="绑定成功",
                        data=dict(next=target_next or "/"),
                    ),
                )
            except ApiError as e:
                raise

        elif action == "create":
            # 直接创建新账号
            nickname = request.form.get("nickname", "").strip() or userinfo.get(
                "name", ""
            )
            try:
                add_profile(
                    account=userinfo["account"],
                    credential=access_token,
                    nickname=nickname,
                    bio="",
                    gender=userinfo.get("gender", 2),
                    avatar=userinfo.get("picture", ""),
                    location=userinfo.get("location", ""),
                )
            except PassportError as e:
                raise ApiError(f"创建账号失败: {e}")

            # 清除 Redis 并生成登录态
            rdb.delete(key)
            try:
                auth = get_account(userinfo["account"])
                if auth:
                    RecordLoginInterface(
                        uid=auth["uid"],
                        account=userinfo["account"],
                        method=f"oauth2_{provider}",
                        ip=get_ip(),
                        ua=request.headers.get("User-Agent", ""),
                        accept_lang=request.headers.get("Accept-Language", ""),
                    )
                return auto_set_user_state(
                    userinfo["account"],
                    7200,
                    dict(
                        success=True,
                        msg="创建成功",
                        data=dict(next=target_next or "/"),
                    ),
                )
            except ApiError as e:
                raise ApiError(f"设置登录态失败: {e}")

        else:
            raise ApiError("无效操作")

    # GET: 展示页面
    return render_template(
        "oauth2go.j2",
        key=key,
        provider=provider,
        tpid=userinfo.get("tpid", ""),
        name=userinfo.get("name", ""),
        email=userinfo.get("email", ""),
        picture=userinfo.get("picture", ""),
    )


@bp.route("/user/profile", methods=["GET", "POST"])
@login_required
def profile():
    """登录后个人主页：GET 展示用户资料及绑定账号，POST 更新资料。"""
    uid = g.user["uid"]

    if request.method == "POST":
        nickname = request.form.get("nickname", "").strip()
        bio = request.form.get("bio", "").strip()
        avatar = request.form.get("avatar", "").strip()
        location = request.form.get("location", "").strip()
        gender = int(request.form.get("gender", 2))

        try:
            update_profile(
                uid,
                nickname=nickname,
                bio=bio,
                gender=gender,
                avatar=avatar,
                location=location,
            )
            return redirect(
                url_for(".profile")
                + "?"
                + urlencode({"msg": "个人资料更新成功", "msg_type": "success"})
            )
        except Exception as e:
            return redirect(
                url_for(".profile")
                + "?"
                + urlencode({"msg": f"更新失败: {e}", "msg_type": "danger"})
            )

    msg = request.args.get("msg", "")
    msg_type = request.args.get("msg_type", "")

    # GET
    profile_data = get_user_by_uid(uid)
    if not profile_data:
        return redirect(
            url_for(".index")
            + "?"
            + urlencode({"msg": "用户信息不存在", "msg_type": "danger"})
        )

    accounts = list_accounts(uid)
    oauth2_providers = list_oauth2_providers()
    login_records = list_login_records(uid, limit=10)
    return render_template(
        "profile.j2",
        profile=profile_data,
        accounts=accounts,
        oauth2_providers=oauth2_providers,
        login_records=login_records,
        msg=msg,
        msg_type=msg_type,
    )


@bp.get("/user/oidc/client")
@login_required
def oidc_client():
    """OIDC 客户端管理页面。"""
    return render_template("oidc.j2")


@bp.get("/user/oauth/authorizations")
@login_required
def oauth_authorizations():
    """我的授权页面——查看并管理已授权的 OIDC 客户端。"""
    return render_template("oauth_authorizations.j2")
