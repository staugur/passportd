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

import json
from typing import Union, Dict, Any
from os.path import join
from secrets import token_urlsafe
from urllib.parse import urlencode
from threading import Thread

from flask import url_for, g, redirect, request
from jinja2 import Environment, FileSystemLoader
from authlib.integrations.flask_client import OAuth

from ..basis.mixin import (
    SapicUploadMixIn,
    LocalUploadMixIn,
    SMTPMixIn,
    SpugMixIn,
    IPQueryMixIn,
)
from ..basis.conf import config
from ..basis.vars import (
    ApiRespType,
    PROC_NAME,
    APP_DIR,
    OAuthUserInfoType,
)
from ..basis.common import new_res
from ..basis.errors import PassportError, ParamError, ApiError, RunError
from ..utils.common import (
    logger,
    rdb,
    rsa_decrypt,
    is_valid_http_url,
    parse_user_agent,
    generate_fingerprint,
)
from ..utils.web import set_user_state, is_safe_url, get_ip
from ..models.user import (
    login,
    list_users,
    list_accounts,
    get_account,
    add_account,
    add_profile,
    generate_jwt,
    record_login,
)


def RegisterInterface(
    account: str, password: str, **profile: Dict[str, Union[str, int]]
) -> ApiRespType:
    """用户注册接口。

    :param account: 用户账号（username / email / mobile 或 OAuthName.tpid 格式）
    :param password: 密码凭证（本地账号为明文密码，第三方为 access_token）
    :param profile: 其他用户资料字段（nickname, bio, gender, avatar, location 等）
    :returns: 标准 API 响应
    """
    res = new_res()
    try:
        ret = add_profile(account, password, **profile)  # type: ignore
    except PassportError as e:
        res.update(message=str(e))
    except Exception as e:
        logger.error(e, exc_info=True)
        res.update(message="Unknown error, registration failed")
    else:
        if ret is True:
            res.update(success=True)
        else:
            res.update(message="Registration failed")
    return res


def LoginInterface(account: str, password: str) -> ApiRespType:
    """用户登录接口。

    :param account: 用户账号（username / email / mobile 或 OAuthName.tpid 格式）
    :param password: 密码凭证
    :returns: 标准 API 响应
    """
    res = new_res()
    try:
        ret = login(account, password)
    except PassportError as e:
        res.update(message=str(e))
    else:
        if ret is True:
            res.update(success=True)
        else:
            res.update(message="Verification failed")
    return res


class UserinfoInterface(object):
    """用户信息接口"""

    def list_users(self) -> ApiRespType:
        """列出所有用户。

        :returns: 标准 API 响应，data 为用户列表
        """
        res = new_res()
        res.update(data=list_users(), success=True)
        return res

    def list_accounts(self, uid: str) -> ApiRespType:
        """列出指定用户的所有关联账号。

        :param uid: 用户唯一标识符
        :returns: 标准 API 响应，data 为账号列表
        """
        res = new_res()
        res.update(data=list_accounts(uid), success=True)
        return res


class UploadInterface(SapicUploadMixIn, LocalUploadMixIn):
    """上传图片接口"""

    def upload_base64_image(self, base64_image: str) -> ApiRespType:
        """上传 base64 编码的图片。

        根据 ``UPLOAD_METHOD`` 配置选择上传方式（sapic 或 local）。

        :param base64_image: Data URI 格式的 base64 图片编码
        :returns: 标准 API 响应，data 中包含图片 URL
        """
        res = new_res()
        if config["UPLOAD_METHOD"] == "sapic":
            try:
                url = self.sapic_base64_upload(base64_image)
            except PassportError as e:
                res["message"] = str(e)
            else:
                res.update(success=True, data=dict(url=url))
        elif config["UPLOAD_METHOD"] == "local":
            try:
                name = self.local_base64_upload(base64_image)
            except PassportError as e:
                res["message"] = str(e)
            else:
                url = url_for("root.front.uploaded", filename=name)
                res.update(success=True, data=dict(url=url))
        else:
            res.update(message="Unsupported upload method")
        return res


class VCodeInterface(SMTPMixIn, SpugMixIn):
    """发送邮件或短信验证码接口"""

    def send_email(self, to_addr: str, code: str) -> ApiRespType:
        """发送验证码邮件。

        根据 ``EMAIL_PROVIDER`` 配置选择发送方式，模板为 ``vcode.j2``。

        :param str to_addr: 收件人邮箱地址
        :param str code: 验证码字符串
        :returns: 标准 API 响应
        """
        res = new_res()
        try:
            if not code:
                raise PassportError("Verification code is empty")
            if not to_addr:
                raise PassportError("Email address is empty")

            provider = config["EMAIL_PROVIDER"]
            je = Environment(loader=FileSystemLoader(join(APP_DIR, "templates")))
            body = je.get_template("vcode.j2").render(code=code)
            subject = f"验证码 - {PROC_NAME}"

            if provider == "smtp":
                ret = self.smtp_send_email(to_addr, subject, body)
            elif provider == "spug":
                ret = self.spug_send_email(to_addr, subject, body)
            else:
                raise PassportError(f"Unsupported email provider: {provider}")

            res.update(success=ret)
        except Exception as e:
            res.update(message=str(e))
        logger.info(f"send_email to {to_addr}, code: {code}, result: {res}")
        return res

    def send_sms(self, phone: str, code: str) -> ApiRespType:
        """发送短信验证码。

        根据 ``SMS_PROVIDER`` 配置选择发送方式。

        :param str phone: 手机号码
        :param str code: 验证码字符串
        :returns: 标准 API 响应
        """
        res = new_res()
        try:
            if not code:
                raise PassportError("Verification code is empty")
            if not phone:
                raise PassportError("Phone number is empty")

            provider = config["SMS_PROVIDER"]

            if provider == "spug":
                params = {config["SPUG_SMS_VCODE_KEY"]: code}
                ret = self.spug_send_sms(phone, params)
            else:
                raise PassportError(f"Unsupported sms provider: {provider}")

            res.update(success=ret)
        except Exception as e:
            res.update(message=str(e))
        logger.info(f"send_sms to {phone}, code: {code}, result: {res}")
        return res


class OAuthClintInterface(OAuth):
    """OAuth2 客户端接口，管理第三方登录、用户信息解析、账号绑定。"""

    def build_account(self, provider: str, tpid: Union[str | int]) -> str:
        """将第三方登录的 provider 和 tpid 组合成唯一账号。

        :param provider: OAuth 提供商名称（如 github、gitee）
        :param tpid: 第三方平台用户唯一标识符
        :returns: 格式为 ``{provider}.{tpid}`` 的唯一账号字符串
        :raises ParamError: provider 或 tpid 无效时抛出
        """
        # tpid是第三方平台用户唯一标识，微博是uid，QQ是openid，Github/GitEE是id
        return "{}.{}".format(provider.lower(), tpid)

    def genderconverter(self, gender: Union[str, int]) -> int:
        """性别转换，将第三方平台的性别表示统一为内部数值。

        - 男 / man / m / 0 → 1
        - 女 / woman / f / female / 1 → 0
        - 其他 → 2（未知）

        :param gender: 原始性别值（字符串或整数）
        :returns: 内部性别编码（0=女, 1=男, 2=未知）
        """
        if gender in ("男", "man", "m", 0, "0"):
            return 1
        elif gender in ("女", "woman", "f", "female", 1, "1"):
            return 0
        return 2

    def parse_userinfo(
        self, provider: str, userinfo: dict[str, Any]
    ) -> OAuthUserInfoType:
        """解析第三方返回的用户信息，转为统一的 OAuthUserInfoType 格式。

        内置支持 github、gitee、weibo、qq，其他平台可通过 ``parse_userinfo_func`` 回调解析。

        :param provider: OAuth 提供商名称
        :param userinfo: 第三方 API 返回的原始用户信息字典
        :returns: 标准化的 OAuth 用户信息
        :raises ParamError: userinfo 为空或格式无效时抛出
        :raises PassportError: 解析失败时抛出
        """
        if not userinfo or not isinstance(userinfo, dict):
            raise ParamError("Empty or invalid userinfo")
        user = dict(email="", gender=2, name="", picture="", location="")
        try:
            if provider in ("github", "gitee"):
                user.update(
                    account=self.build_account(provider, userinfo["id"]),
                    tpid=userinfo["login"],
                    name=userinfo.get("name") or "",
                    email=userinfo["email"] or "",
                    picture=userinfo.get("avatar_url") or "",
                    location=userinfo.get("location") or "",
                )
            elif provider == "weibo":
                user.update(
                    account=self.build_account(
                        provider, userinfo["id"] or userinfo.get("idstr", "")
                    ),
                    tpid=userinfo.get("screen_name", ""),
                    name=userinfo.get("screen_name") or "",
                    picture=userinfo.get("profile_image_url") or "",
                    location=userinfo.get("location") or "",
                    gender=self.genderconverter(userinfo.get("gender", "")),
                )
            elif provider == "qq":
                avatar = userinfo.get("figureurl_qq_2") or userinfo.get(
                    "figureurl_qq_1", ""
                )
                location = " ".join(
                    filter(
                        None,
                        [userinfo.get("province", ""), userinfo.get("city", "")],
                    )
                )
                user.update(
                    account=self.build_account(provider, userinfo["openid"]),
                    tpid=userinfo.get("nickname", ""),
                    name=userinfo.get("nickname") or "",
                    picture=avatar,
                    location=location,
                    gender=self.genderconverter(userinfo.get("gender", "")),
                )
            else:
                # 非内置支持的第三方登录尝试解析用户信息
                pobj = self._clients.get(provider)
                if pobj and hasattr(pobj, "client_kwargs"):
                    pfunc = pobj.client_kwargs.get("parse_userinfo_func")
                    if callable(pfunc):
                        ret = pfunc(**userinfo)
                        if ret and isinstance(ret, dict):
                            user.update(ret)
        except Exception as e:
            raise PassportError(f"Failed to parse userinfo: {e}")
        else:
            return OAuthUserInfoType(user)  # type: ignore

    def _bind_redirect(self, msg: str, msg_type: str):
        """绑定流程重定向，通过 query string 传递消息。"""
        redirect_url = (
            url_for("root.front.profile")
            + "?"
            + urlencode({"msg": msg, "msg_type": msg_type})
        )
        return redirect(redirect_url)

    def oauth2_authorized_handler(
        self,
        provider: str,
        access_token: str,
        userinfo: OAuthUserInfoType,
    ):
        """OAuth 授权回调处理，执行绑定或自动登录逻辑。

        场景：
        1. **已登录**：检测账号是否已绑定，已绑定则更新凭证，未绑定则新建绑定。
        2. **未登录**：检测账号是否已绑定，已绑定则直接签发登录态，未绑定则跳转 OAuth2 选择页面。

        :param provider: OAuth 提供商名称
        :param access_token: 第三方访问令牌
        :param userinfo: 标准化 OAuth 用户信息
        :returns: Flask redirect 响应
        :raises ParamError: 参数无效时抛出
        """
        if (
            not provider
            or not access_token
            or not userinfo
            or not isinstance(userinfo, dict)
            or "account" not in userinfo
        ):
            raise ParamError("Invalid provider, access_token or userinfo")
        account = userinfo["account"]
        auth_data = get_account(account)

        # 已登录 -> 绑定流程
        if g.signin is True:
            uid = g.user["uid"]

            if auth_data:
                #: 账号已存在，检查是否绑定到其他uid
                if auth_data["uid"] != uid:
                    return self._bind_redirect("该账号已绑定到其他用户", "warning")
                #: 已经绑定到当前uid
                return self._bind_redirect("绑定成功", "success")
            else:
                #: 账号不存在，直接绑定
                try:
                    add_account(uid, account, tpid=userinfo["tpid"])
                except PassportError as e:
                    return self._bind_redirect(str(e), "danger")
                else:
                    return self._bind_redirect("绑定成功", "success")

        # 未登录 -> 关联、生成本地账号流程
        else:
            # 尝试解密 state，如果是passport本身登录解密会失败，OIDC Client则成功。
            redirect_url = url_for("root.front.index")
            try:
                state: str = request.args.get("state", "")
                decrypted_state = rsa_decrypt(state)
                if not isinstance(decrypted_state, str):
                    decrypted_state = decrypted_state.decode("utf-8")
                if (
                    decrypted_state
                    and is_valid_http_url(decrypted_state)
                    and is_safe_url(decrypted_state)
                ):
                    redirect_url = decrypted_state
            except Exception as e:
                logger.info(f"Failed to decrypt or invalid state: {e}")

            if auth_data:
                # 账号已绑定，直接登录并跳转到 next_url
                expire = 7200
                RecordLoginInterface(
                    uid=auth_data["uid"],
                    account=account,
                    method=provider,
                    ip=get_ip(),
                    ua=request.headers.get("User-Agent", ""),
                    accept_lang=request.headers.get("Accept-Language", ""),
                )
                token = generate_jwt(account, expire)
                if not token:
                    raise ApiError("generate cookie failed")
                return set_user_state(token, redirect_url, expire)
            else:
                # 账号未绑定，拦截返回，跳转到OAuth2选择页面（选择绑定本地账号或直接创建用户）
                key = f"oauth2go:{token_urlsafe(32)}"
                rdb.setex(
                    key,
                    600,
                    json.dumps(
                        dict(
                            provider=provider,
                            access_token=access_token,
                            userinfo=userinfo,
                            next_url=redirect_url,
                        )
                    ),
                )
                return redirect(url_for("root.front.oauth2go", key=key))


def RecordLoginInterface(
    uid: str,
    account: str,
    method: str,
    *,
    ip: str = "",
    ua: str = "",
    accept_lang: str = "",
) -> None:
    """在后台线程中解析客户端信息并写入登录记录。

    将 UA 解析、IP 地理位置查询等耗时操作放到独立线程中执行，
    避免阻塞登录响应。daemon 线程执行完毕后由 OS 回收线程栈和资源，
    Thread 对象由 Python GC 自动回收。

    :param uid: 用户 uid
    :param account: 登录账号
    :param method: 登录方式（local / oauth2_github 等）
    :param ip: 客户端 IP
    :param ua: User-Agent 字符串
    :param accept_lang: Accept-Language 请求头
    """

    def _run():
        querier = IPQueryMixIn()
        location = querier.saintic_ip_query(ip)
        if not location:
            location = querier.ip_api_query(ip)
        browser, os_name, device = parse_user_agent(ua)
        fingerprint = generate_fingerprint(ip, ua, accept_lang)
        record_login(
            uid=uid,
            account=account,
            method=method,
            ip=ip,
            location=location,
            user_agent=ua,
            browser=browser,
            os=os_name,
            device=device,
            fingerprint=fingerprint,
        )

    Thread(target=_run, daemon=True).start()


#: OAuth2 Client
OAuthClient = OAuthClintInterface()
