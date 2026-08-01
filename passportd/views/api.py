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

from ..libs.interface import UploadInterface, RegisterInterface
from ..models.user import change_password, list_login_records
from ..models.oidc import (
    create_oauth_client,
    list_oauth_clients,
    update_oauth_client,
    delete_oauth_client,
    count_oauth_authorizations,
)
from ..basis.errors import ApiError, PassportError
from ..basis.vars import JWE_HEADER
from ..basis.common import new_res
from ..utils.web import apilogin_required
from ..utils.common import read_rsa_public_key, parse_encrypted_password

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

    :form account: 用户账号（必填）
    :form password: 密码（必填，明文或 RSA 加密）
    :form repassword: 确认密码
    :form encrypted_password: 加密后的密码（JWE 格式，优先使用）
    :form encrypted_repassword: 加密后的确认密码
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
    nickname = data.get("nickname", "")
    bio = data.get("bio", "")
    gender = data.get("gender", 2)
    avatar = data.get("avatar", "")
    location = data.get("location", "Unknown")
    # deny role from common api

    if not account or not decrypted_password:
        raise ApiError("account and password is required")
    if decrypted_password != decrypted_repassword:
        raise ApiError("password and repassword not match")
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

    :form old_password: 旧密码（明文）
    :form new_password: 新密码（明文）
    :form repassword: 确认新密码（明文）
    :form encrypted_old_password: 加密后的旧密码（JWE 格式，优先使用）
    :form encrypted_new_password: 加密后的新密码（JWE 格式，优先使用）
    :form encrypted_repassword: 加密后的确认新密码（JWE 格式，优先使用）
    :returns: 操作结果 JSON
    """
    data = request.form.to_dict()
    uid = g.user["uid"]
    account = g.user["account"]

    # 解密密码（优先加密格式）
    old_pwd = parse_encrypted_password(
        data.get("encrypted_old_password", "")
    ) or data.get("old_password", "")
    new_pwd = parse_encrypted_password(
        data.get("encrypted_new_password", "")
    ) or data.get("new_password", "")
    repassword = parse_encrypted_password(
        data.get("encrypted_repassword", "")
    ) or data.get("repassword", "")

    if not old_pwd or not new_pwd:
        raise ApiError("old_password and new_password are required")
    if new_pwd != repassword:
        raise ApiError("new_password and repassword do not match")
    if len(new_pwd) < 6:
        raise ApiError("new_password must be at least 6 characters")

    try:
        ret = change_password(uid, account, old_pwd, new_pwd)
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
