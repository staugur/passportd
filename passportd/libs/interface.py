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
    PASSKEY_RP_NAME,
)
from ..basis.common import new_res
from ..basis.errors import PassportError, ParamError, ApiError, RunError, PasskeyError
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
            if provider == "smtp":
                je = Environment(loader=FileSystemLoader(join(APP_DIR, "templates")))
                body = je.get_template("vcode.j2").render(code=code)
                subject = f"验证码 - {PROC_NAME}"
                ret = self.smtp_send_email(to_addr, subject, body)
            elif provider == "spug":
                ret = self.spug_send_email(to_addr, code)
            else:
                raise PassportError(f"Unsupported email provider: {provider}")

            res.update(success=ret)
        except Exception as e:
            res.update(message=str(e))
        logger.info(
            f"send_email to {to_addr}, provider: {config['EMAIL_PROVIDER']}, result: {res}"
        )
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
                ret = self.spug_send_sms(phone, code)
            else:
                raise PassportError(f"Unsupported sms provider: {provider}")

            res.update(success=ret)
        except Exception as e:
            res.update(message=str(e))
        logger.info(
            f"send_sms to {phone}, provider: {config['SMS_PROVIDER']}, result: {res}"
        )
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


class PasskeyInterface(object):
    """WebAuthn Passkey 接口，管理密码密钥的注册与认证。

    使用 ``webauthn`` 库实现 WebAuthn Level 2 协议，支持 platform（指纹/面容）
    和 cross-platform（USB 安全密钥）认证器。
    """

    def __init__(self):
        self._rp_id: str = ""
        self._rp_name: str = ""
        self._origin: str = ""
        self._initialized: bool = False

    def _ensure_config(self):
        """确保配置已初始化（首次调用时从请求上下文获取）。"""
        if self._initialized:
            return
        from ..utils.web import get_rp_id, get_origin

        self._rp_id = get_rp_id()
        self._rp_name = config.get("PASSKEY_RP_NAME", PASSKEY_RP_NAME)
        self._origin = get_origin()
        self._initialized = True

    @property
    def rp_id(self) -> str:
        self._ensure_config()
        return self._rp_id

    @property
    def rp_name(self) -> str:
        self._ensure_config()
        return self._rp_name

    @property
    def origin(self) -> str:
        self._ensure_config()
        return self._origin

    # ---- 注册 ----

    def generate_registration_options(
        self, uid: str, account: str, display_name: str = ""
    ) -> dict:
        """生成 Passkey 注册选项，下发给浏览器。

        浏览器收到后需调用 ``navigator.credentials.create({ publicKey: options })``。

        :param uid: 用户唯一标识符
        :param account: 用户账号名（username）
        :param display_name: 展示名称，为空时使用 account
        :returns: PublicKeyCredentialCreationOptions 转 JSON 后的字典
        :raises PasskeyError: 配置或生成失败时抛出
        """
        from webauthn import generate_registration_options
        from webauthn.helpers.structs import AuthenticatorSelectionCriteria
        from webauthn.helpers import bytes_to_base64url
        from ..utils.common import (
            base64url_encode,
            generate_passkey_challenge,
            save_passkey_challenge,
        )
        from ..models.model import PasskeyCredential

        try:
            # 获取已注册的凭证 ID（用于排除已有设备）
            existing_creds = PasskeyCredential.select().where(
                PasskeyCredential.uid == uid
            )
            exclude_credentials = []
            for cred in existing_creds:
                exclude_credentials.append(
                    {
                        "id": cred.credential_id,
                        "type": "public-key",
                        "transports": ["internal", "hybrid"],
                    }
                )

            options = generate_registration_options(
                rp_id=self.rp_id,
                rp_name=self.rp_name,
                user_id=uid.encode("utf-8"),
                user_name=account,
                user_display_name=display_name or account,
                exclude_credentials=exclude_credentials if exclude_credentials else None,
                authenticator_selection=AuthenticatorSelectionCriteria(
                    authenticator_attachment="platform",
                    resident_key="required",
                    user_verification="preferred",
                ),
                attestation="none",
            )

            # 缓存 challenge
            challenge_b64 = bytes_to_base64url(options.challenge)
            save_passkey_challenge(uid, options.challenge)

            return {
                "rp": {"name": options.rp.name, "id": options.rp.id},
                "user": {
                    "id": base64url_encode(uid.encode("utf-8")),
                    "name": options.user.name,
                    "displayName": options.user.display_name,
                },
                "challenge": challenge_b64,
                "pubKeyCredParams": [
                    {"type": "public-key", "alg": -7},
                    {"type": "public-key", "alg": -257},
                ],
                "timeout": 60000,
                "excludeCredentials": [
                    {
                        "id": c["id"],
                        "type": c["type"],
                        "transports": c.get("transports", []),
                    }
                    for c in exclude_credentials
                ],
                "authenticatorSelection": {
                    "authenticatorAttachment": "platform",
                    "residentKey": "required",
                    "userVerification": "preferred",
                },
                "attestation": "none",
            }
        except Exception as e:
            logger.error(f"generate_registration_options error: {e}", exc_info=True)
            raise PasskeyError(f"Failed to generate registration options: {e}") from e

    def verify_registration_response(
        self, uid: str, credential_json: dict
    ) -> dict:
        """验证浏览器返回的注册结果，成功则存储公钥。

        :param uid: 用户唯一标识符
        :param credential_json: 浏览器返回的 ``PublicKeyCredential`` JSON
        :returns: 包含 credential_id 和 device_name 的字典
        :raises PasskeyError: 验证失败时抛出
        """
        from webauthn import verify_registration_response
        from webauthn.helpers import bytes_to_base64url
        from ..utils.common import (
            base64url_decode,
            get_passkey_challenge,
        )
        from ..models.model import PasskeyCredential
        from ..basis.common import now

        try:
            # 读取并清除 challenge（一次性使用）
            expected_challenge = get_passkey_challenge(uid)
            if not expected_challenge:
                raise PasskeyError("Registration challenge expired, please try again")

            verification = verify_registration_response(
                credential=credential_json,
                expected_challenge=expected_challenge,
                expected_rp_id=self.rp_id,
                expected_origin=self.origin,
            )

            # 解析设备名称
            device_name = self._parse_device_name(
                credential_json.get("response", {}).get("clientDataJSON", ""),
                credential_json,
                verification,
            )

            # 判断凭证类型
            is_platform = (
                credential_json.get("authenticatorAttachment", "")
                == "platform"
            )

            # 存储凭证
            PasskeyCredential.create(
                credential_id=bytes_to_base64url(verification.credential_id),
                uid=uid,
                public_key=verification.credential_public_key,
                sign_count=verification.sign_count,
                device_name=device_name,
                credential_type="platform" if is_platform else "cross-platform",
                ctime=now(),
            )

            return {
                "credential_id": bytes_to_base64url(verification.credential_id),
                "device_name": device_name,
            }
        except PasskeyError:
            raise
        except Exception as e:
            logger.error(f"verify_registration_response error: {e}", exc_info=True)
            raise PasskeyError(f"Failed to verify registration: {e}") from e

    # ---- 认证（登录）----

    def generate_authentication_options(self, uid: str = "") -> dict:
        """生成 Passkey 认证选项，下发给浏览器进行登录。

        浏览器收到后需调用 ``navigator.credentials.get({ publicKey: options })``。

        :param uid: 可选的用户标识符，为空时使用无用户名登录（resident key）
        :returns: PublicKeyCredentialRequestOptions 转 JSON 后的字典
        :raises PasskeyError: 配置或生成失败时抛出
        """
        from webauthn import generate_authentication_options
        from webauthn.helpers import bytes_to_base64url
        from ..utils.common import (
            generate_passkey_challenge,
            save_passkey_challenge,
        )
        from ..models.model import PasskeyCredential

        try:
            # 如果指定了用户，限定该用户的凭证
            allow_credentials = None
            if uid:
                existing_creds = PasskeyCredential.select().where(
                    PasskeyCredential.uid == uid
                )
                cred_list = list(existing_creds)
                if cred_list:
                    allow_credentials = []
                    for cred in cred_list:
                        allow_credentials.append(
                            {
                                "id": cred.credential_id,
                                "type": "public-key",
                                "transports": ["internal", "hybrid"],
                            }
                        )

            options = generate_authentication_options(
                rp_id=self.rp_id,
                allow_credentials=allow_credentials,
                user_verification="preferred",
            )

            # 缓存 challenge，key 使用 uid 或临时 session
            # 登录阶段 challenge 不需绑定用户，用统一 key
            challenge_key = uid or "__anonymous__"
            save_passkey_challenge(f"login:{challenge_key}", options.challenge)

            result = {
                "challenge": bytes_to_base64url(options.challenge),
                "timeout": 60000,
                "rpId": self.rp_id,
                "userVerification": "preferred",
            }
            if allow_credentials:
                result["allowCredentials"] = allow_credentials

            return result
        except Exception as e:
            logger.error(f"generate_authentication_options error: {e}", exc_info=True)
            raise PasskeyError(
                f"Failed to generate authentication options: {e}"
            ) from e

    def verify_authentication_response(
        self, credential_json: dict
    ) -> dict:
        """验证浏览器返回的认证结果，认证成功返回用户信息。

        :param credential_json: 浏览器返回的 ``PublicKeyCredential`` JSON
        :returns: 包含 uid 和 account 的字典
        :raises PasskeyError: 验证失败时抛出
        """
        from webauthn import verify_authentication_response
        from webauthn.helpers import bytes_to_base64url
        from ..utils.common import base64url_decode, get_passkey_challenge
        from ..models.model import PasskeyCredential

        try:
            # 根据 credential_id 查找凭证
            try:
                passkey = PasskeyCredential.get(
                    PasskeyCredential.credential_id == credential_json.get("id", "")
                )
            except PasskeyCredential.DoesNotExist:
                raise PasskeyError("Passkey credential not found")

            # 读取 challenge（先尝试绑定用户，再尝试匿名）
            expected_challenge = get_passkey_challenge(f"login:{passkey.uid}")
            if not expected_challenge:
                expected_challenge = get_passkey_challenge("login:__anonymous__")
            if not expected_challenge:
                raise PasskeyError(
                    "Authentication challenge expired, please try again"
                )

            verification = verify_authentication_response(
                credential=credential_json,
                expected_challenge=expected_challenge,
                expected_rp_id=self.rp_id,
                expected_origin=self.origin,
                credential_public_key=passkey.public_key,
                credential_current_sign_count=passkey.sign_count,
            )

            # 更新签名计数器和最近使用时间
            from ..basis.common import now

            PasskeyCredential.update(
                sign_count=verification.new_sign_count,
                last_used_at=now(),
            ).where(
                PasskeyCredential.credential_id == passkey.credential_id
            ).execute()

            return {
                "uid": passkey.uid,
                "credential_id": passkey.credential_id,
                "device_name": passkey.device_name,
            }
        except PasskeyError:
            raise
        except Exception as e:
            logger.error(
                f"verify_authentication_response error: {e}", exc_info=True
            )
            raise PasskeyError(f"Failed to verify authentication: {e}") from e

    # ---- 凭证管理 ----

    def list_credentials(self, uid: str) -> list:
        """列出用户绑定的所有 Passkey 凭证。

        :param uid: 用户唯一标识符
        :returns: 凭证列表
        """
        from ..models.model import PasskeyCredential

        creds = (
            PasskeyCredential.select()
            .where(PasskeyCredential.uid == uid)
            .order_by(PasskeyCredential.ctime.desc())
        )
        return [
            {
                "credential_id": c.credential_id,
                "device_name": c.device_name,
                "credential_type": c.credential_type,
                "sign_count": c.sign_count,
                "ctime": c.ctime,
                "last_used_at": c.last_used_at,
            }
            for c in creds
        ]

    def delete_credential(self, uid: str, credential_id: str) -> bool:
        """删除用户的指定 Passkey 凭证。

        :param uid: 用户唯一标识符
        :param credential_id: 凭证 ID（base64url）
        :returns: 是否删除成功
        """
        from ..models.model import PasskeyCredential

        deleted = (
            PasskeyCredential.delete()
            .where(
                PasskeyCredential.uid == uid,
                PasskeyCredential.credential_id == credential_id,
            )
            .execute()
        )
        return deleted > 0

    # AAGUID → 设备/服务名称映射
    # 参考: https://github.com/passkeydeveloper/passkey-authenticator-aaguids
    _AAGUID_MAP: dict[str, str] = {
        # 密码管理器
        "b93fd961-f2e6-462f-b122-82002247de78": "Bitwarden / Vaultwarden",
        "d548826e-79b4-db40-a3d8-11116f7e8349": "Bitwarden / Vaultwarden",
        "b537cfd0-3bf2-42a4-91f0-cf697de23f5e": "1Password (Desktop)",
        "53414d53-4241-4700-8137-934f001fe977": "1Password (Browser)",
        "66a0c194-51f1-4503-b99e-5271bd8f8bfe": "Dashlane",
        # 平台认证器
        "6028b017-b1d4-4c02-b4b3-afcdafc96bb2": "Windows Hello",
        "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4": "iCloud Keychain",
        "8836336a-f590-0921-301d-46427531eee6": "Apple Touch ID",
        "175b38db-76b8-59dc-b0a8-2f4f10dd5d58": "Apple Passkey (iOS/macOS)",
        # Google
        "930b2fd6-4f21-41f1-9437-15bfce5aa3f2": "Google Password Manager (Android)",
        "b84e4048-15dc-4289-8b84-6383fb6a8b2c": "Google Password Manager (Desktop)",
        "adce0002-35bc-c60a-648b-0b25f1f05503": "Chrome on Android",
        # 硬件密钥
        "fa2b99c1-71e8-5489-a0d4-e53f79e7d01a": "YubiKey 5 (FIDO2)",
        "73bb0cd4-e502-49b8-9c6f-b59445bf720b": "YubiKey Bio",
        "d548826e-79b4-db40-a3d8-1116ea7b1344": "YubiKey 5Ci",
        "d7a423f3-71e9-4181-82a4-0fae6878e507": "Feitian BioPass",
        "e1a96183-5016-4f24-b55b-e3ae23614cc6": "SoloKey",
        "887f9bfb-1f31-48bf-877c-1ac1bcb2f64c": "Nitrokey",
    }

    @staticmethod
    def _parse_device_name(
        client_data_json_base64url: str,
        credential_json: dict | None = None,
        verification=None,
    ) -> str:
        """从 clientDataJSON 解析设备名称。

        优先解析 User-Agent → AAGUID 精确匹配 → authenticatorAttachment
        → credential_device_type，逐步降级。
        """
        from ..utils.common import base64url_decode
        from ..utils.common import parse_user_agent
        try:
            data = base64url_decode(client_data_json_base64url)
            client_data = json.loads(data.decode("utf-8"))
            # 1. 优先解析 UA（浏览器）
            ua = client_data.get("userAgent", "")
            if ua:
                browser, os_name, _ = parse_user_agent(ua)
                if browser != "Unknown":
                    return f"{browser} on {os_name}"

            # 2. AAGUID 精确匹配（密码管理器 / 硬件密钥）
            if verification is not None:
                aaguid = getattr(verification, "aaguid", None)
                if aaguid and aaguid != "00000000-0000-0000-0000-000000000000":
                    name = PasskeyClient._AAGUID_MAP.get(aaguid, "")
                    if name:
                        return name
                    logger.debug("Unknown AAGUID: %s", aaguid)

            # 3. 无 UA / 未知 AAGUID 时从其他来源推断名称
            parts = []

            if credential_json:
                attachment = credential_json.get("authenticatorAttachment", "")
                if attachment == "platform":
                    parts.append("Platform")
                elif attachment == "cross-platform":
                    parts.append("Cross-Platform")

            if verification is not None:
                dev_type = getattr(verification, "credential_device_type", None)
                if dev_type is not None:
                    type_name = getattr(dev_type, "value", str(dev_type))
                    parts.append(type_name.replace("_", " ").title())
                backed_up = getattr(verification, "credential_backed_up", False)
                if backed_up:
                    parts.append("Synced")

            if parts:
                return " ".join(parts) + " Authenticator"

            # 4. transports 信息
            if credential_json:
                transports = (
                    credential_json.get("response", {}).get("transports", []) or []
                )
                if transports:
                    return f"Security Key ({', '.join(transports)})"

            logger.debug(
                "_parse_device_name fallback: client_data=%s credential_json=%s",
                client_data, credential_json,
            )
            return "Unknown device"
        except Exception:
            logger.exception("_parse_device_name error")
            return "Unknown device"


#: OAuth2 Client
OAuthClient = OAuthClintInterface()

#: Passkey 接口实例
PasskeyClient = PasskeyInterface()
