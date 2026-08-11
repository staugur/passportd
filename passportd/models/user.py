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

import secrets
from typing import Union, List
from binascii import Error as BinasciiError

from werkzeug.security import generate_password_hash, check_password_hash
from playhouse.shortcuts import model_to_dict

from .model import User, Auth, AuditLog, LoginRecord, OAuthToken, OAuthAuthorization, PasskeyCredential, UserSession, db
from ..basis.mixin import GetItemMixIn
from ..basis.errors import AuthError, JWTError, ParamError
from ..basis.vars import COMMON_DICT_TYPE
from ..basis.common import now
from ..basis.conf import config
from ..utils.common import parse_user_agent
from ..utils.common import (
    is_local_account,
    parse_account_classify,
    gen_uid,
    jwt_encode,
    jwt_decode,
    jwt_decode_payload_without_verify,
    is_valid_user_role,
    is_valid_http_url,
    logger,
)


def check_credential_rule(pwd: str) -> bool:
    """检查密码凭证长度是否符合规范（6~32 个字符）。

    :param pwd: 密码凭证字符串
    :returns: 符合返回 True，否则 False
    """
    return 6 <= len(pwd) <= 32 if isinstance(pwd, str) else False


def has_uid(uid: str) -> bool:
    """检查指定 uid 是否在 User 表中存在。

    :param uid: 用户唯一标识符（22 位字符串）
    :returns: 存在返回 True，否则 False
    """
    if len(uid) != 22:
        return False
    return User.select().where(User.uid == uid).exists()


def list_users() -> List[COMMON_DICT_TYPE]:
    """列出所有用户。

    :returns: 用户信息字典列表（已剔除 password_hash）
    """
    return [model_to_dict(u, exclude=[User.password_hash]) for u in User.select()]


def get_user_email(uid: str) -> Union[None, str]:
    """根据 uid 获取用户绑定的邮箱地址。

    从 Auth 表中查找 ``classify == "email"`` 的账号并返回。

    :param uid: 用户唯一标识符（22 位字符串）
    :returns: 邮箱字符串，不存在时返回 None
    """
    try:
        a = Auth.get((Auth.uid == uid) & (Auth.classify == "email"))
        return a.account
    except Auth.DoesNotExist:
        return None


def get_user_by_uid(uid: str) -> Union[None, COMMON_DICT_TYPE]:
    """根据 uid 获取用户基本信息。

    返回字段: uid, nickname, bio, gender, avatar, location, status, role

    :param uid: 用户唯一标识符（22 位字符串）
    :returns: 用户信息字典，不存在时返回 None
    """
    try:
        u = User.get(User.uid == uid)
        return dict(
            uid=u.uid,
            nickname=u.nickname,
            bio=u.bio,
            gender=u.gender,
            avatar=u.avatar,
            location=u.location,
            status=u.status,
            role=u.role,
            ctime=u.ctime,
            mtime=u.mtime,
        )
    except User.DoesNotExist:
        return None


def has_account(account: str) -> bool:
    """检查指定账号是否在 Auth 表中存在。

    :param account: 账号字符串
    :returns: 存在返回 True，否则 False
    """
    return Auth.select().where(Auth.account == account).exists()


def get_account(account: str) -> Union[None, COMMON_DICT_TYPE]:
    """根据账号获取对应的 Auth 记录。

    :param account: 账号字符串
    :returns: Auth 记录字典，不存在时返回 None
    """
    try:
        ret = Auth.get(Auth.account == account)
        return model_to_dict(ret)
    except Auth.DoesNotExist:
        return None


def list_accounts(uid: str) -> List[COMMON_DICT_TYPE]:
    """列出指定用户的所有关联账号。

    :param uid: 用户唯一标识符
    :returns: 账号信息字典列表
    """
    return [model_to_dict(u) for u in Auth.select().where(Auth.uid == uid)]


def add_profile(
    account: str,
    credential: str,
    *,
    nickname: str = "",
    bio: str = "",
    gender: int = 2,
    avatar: str = "",
    location: str = "",
    role: str = "User",
) -> bool:
    """注册新用户资料（可源于本地和第三方），既无User又无Auth记录。

    如果是本地化账号，account应该是username格式，密码哈希存入 User.password_hash；
    如果是第三方账号，account应该是OAuthName.tpid格式，access_token 不入库。
    """
    if not account or not check_credential_rule(credential):
        raise ParamError("Invalid account or credential")
    if len(account) < 4:
        raise ParamError("account length too short")
    if not is_valid_user_role(role):
        raise ParamError("Invalid user role")
    classify = parse_account_classify(account)
    if not classify:
        raise ParamError("Invalid account type")
    try:
        gender = int(gender)
        if gender not in (0, 1, 2):
            raise ParamError("Invalid gender value")
    except ValueError:
        raise ParamError("Invalid gender type")
    if avatar:
        if not is_valid_http_url(avatar):
            raise ParamError("Invalid avatar url")
    if has_account(account):
        raise AuthError("The account already exists")
    password_hash = None
    if is_local_account(account):
        password_hash = generate_password_hash(credential)
    uid = gen_uid()
    ctime = now()
    try:
        with db.atomic():
            User.create(
                uid=uid,
                nickname=nickname,
                bio=bio,
                gender=gender,
                avatar=avatar,
                location=location,
                password_hash=password_hash,
                ctime=ctime,
                role=role,
            )
            Auth.create(
                uid=uid,
                account=account,
                classify=classify,
                ctime=ctime,
            )
    except Exception as e:
        raise AuthError(e)
    else:
        return True


def add_account(
    uid: str,
    account: str,
    *,
    tpid: str = "",
) -> bool:
    """为已存在用户添加新的认证方式（Auth 记录）。

    支持本地账号（username / email / mobile）和第三方账号绑定。
    第三方账号必须提供 ``tpid``。
    密码由 User.password_hash 统一管理，此处不处理 credential。

    :param uid: 用户唯一标识符
    :param account: 新账号
    :param tpid: 第三方平台用户唯一标识（第三方账号必须提供）
    :returns: 添加成功返回 True
    :raises ParamError: 参数校验失败
    :raises AuthError: 账号已存在或 uid 不存在
    """
    if not account:
        raise ParamError("Invalid account")
    if len(account) < 4:
        raise ParamError("account length too short")
    classify = parse_account_classify(account)
    if not classify:
        raise ParamError("Invalid account type")
    if not is_local_account(account) and not tpid:
        raise ParamError("tpid is required for third-party account")
    if has_account(account):
        raise AuthError("The account already exists")
    if not has_uid(uid):
        raise AuthError("Not found uid")
    try:
        Auth.create(
            uid=uid,
            account=account,
            tpid=tpid,
            classify=classify,
            ctime=now(),
        )
    except Exception as e:
        raise AuthError(e)
    else:
        return True


def delete_account(uid: str, account: str) -> int:
    """解绑用户的某个邮箱、手机号或第三方认证方式。

    限制：
    - 只能解绑邮箱、手机号或第三方登录类型
    - 至少保留一条 Auth 记录
    - ``account`` 必须属于该用户

    :param uid: 用户唯一标识符
    :param account: 待解绑的账号
    :returns: 删除的记录数
    :raises ParamError: 参数校验失败
    :raises AuthError: 不能解绑用户名或这是最后一条记录
    """
    if not uid or len(uid) != 22:
        raise ParamError("Invalid uid")
    if not account:
        raise ParamError("Invalid account")

    classify = parse_account_classify(account)
    if classify not in ("email", "mobile", "3rd"):
        raise ParamError("仅支持解绑邮箱、手机号或第三方账号")

    if not has_uid(uid):
        raise AuthError("Not found uid")

    accounts = list_accounts(uid)
    if len(accounts) <= 1:
        raise AuthError("至少保留一条绑定记录")

    # 确认该账号属于当前用户
    owner = [a for a in accounts if a["account"] == account]
    if not owner:
        raise AuthError("该账号不属于当前用户")

    result = (
        Auth.delete()
        .where((Auth.uid == uid) & (Auth.account == account))
        .execute()
    )
    return result


def delete_user_data(
    uid: str,
    ip: str = "",
    user_agent: str = "",
) -> bool:
    """注销账号，级联删除用户所有数据。

    前置条件：
    - 用户名下不能有 OIDC 客户端（需先手动删除）

    删除顺序：
    - 写入 account_delete 审计日志
    - UserSession（活跃会话）
    - PasskeyCredential（Passkey 凭证）
    - OAuthToken（OIDC 令牌）
    - OAuthAuthorization（OIDC 授权记录）
    - LoginRecord（登录记录）
    - Auth（认证方式）
    - User（用户主记录）

    注意：审计日志（AuditLog）不会被删除，保留为注销记录。

    :param uid: 用户唯一标识符
    :param ip: 客户端 IP（用于审计日志）
    :param user_agent: User-Agent（用于审计日志）
    :returns: 删除成功返回 True
    :raises ParamError: uid 无效
    :raises AuthError: uid 不存在 / 存在 OIDC 客户端 / 数据库操作失败
    """
    from .oidc import list_oauth_clients  # 延迟导入，避免循环引用
    from .audit import record_audit_log

    if not uid or len(uid) != 22:
        raise ParamError("Invalid uid")
    if not has_uid(uid):
        raise AuthError("Not found uid")

    # 检查是否有 OIDC 客户端
    if list_oauth_clients(uid):
        raise AuthError(
            "请先删除名下的所有 OIDC 应用客户端后再注销账号"
        )

    try:
        with db.atomic():
            # 先写入注销审计日志（保留不删除）
            record_audit_log(
                uid=uid,
                action="account_delete",
                detail={"method": "password_verified"},
                ip=ip,
                user_agent=user_agent,
            )
            UserSession.delete().where(
                UserSession.uid == uid
            ).execute()
            PasskeyCredential.delete().where(
                PasskeyCredential.uid == uid
            ).execute()
            OAuthToken.delete().where(OAuthToken.uid == uid).execute()
            OAuthAuthorization.delete().where(
                OAuthAuthorization.uid == uid
            ).execute()
            LoginRecord.delete().where(LoginRecord.uid == uid).execute()
            Auth.delete().where(Auth.uid == uid).execute()
            User.delete().where(User.uid == uid).execute()
    except Exception as e:
        raise AuthError(f"注销账号失败: {e}")
    else:
        return True


def update_profile(
    uid: str,
    *,
    nickname: str = "",
    bio: str = "",
    gender: int = -1,
    avatar: str = "",
    location: str = "",
    status: int = -1,
    role: str = "",
) -> bool:
    """更新用户资料。

    role 支持三种操作：
    - 替换：直接传角色名，如 ``"Admin"``
    - 追加：以 ``+`` 开头，如 ``"+Admin"``
    - 移除：以 ``-`` 开头，如 ``"-Admin"``

    :param uid: 用户唯一标识符
    :param nickname: 新昵称（空字符串表示不修改）
    :param bio: 新简介
    :param gender: 性别（-1 表示不修改）
    :param avatar: 新头像 URL
    :param location: 新地区
    :param status: 状态（-1 表示不修改，0=禁用, 1=启用）
    :param role: 角色操作
    :returns: 更新成功返回 True
    :raises AuthError: uid 不存在或数据库操作失败
    :raises ParamError: 参数校验失败
    """
    if not has_uid(uid):
        raise AuthError("Not found user id")
    if gender not in (-1, 0, 1, 2):
        raise ParamError("Invalid gender value")
    if status not in (-1, 0, 1):
        raise ParamError("Invalid status value")
    if role and not is_valid_user_role(role):
        raise ParamError("Invalid role value")
    try:
        u = User.get(User.uid == uid)
        if nickname:
            u.nickname = nickname
        if bio:
            u.bio = bio
        if gender != -1:
            u.gender = gender
        if avatar:
            u.avatar = avatar
        if location:
            u.location = location
        if status != -1:
            u.status = status
        if role:
            if role.startswith("+"):
                # 添加角色
                roles = role.lstrip("+").split(" ")
                current_roles = u.role.split(" ") if u.role else []
                roles = current_roles + roles
            elif role.startswith("-"):
                # 删除角色
                current_roles = u.role.split(" ") if u.role else []
                for r in role.lstrip("-").split(" "):
                    if r in current_roles:
                        current_roles.remove(r)
                roles = current_roles
            else:
                # 替换角色
                roles = role.split(" ")
            u.role = " ".join(roles)
        u.mtime = now()
        u.save()
    except Exception as e:
        raise AuthError(e)
    else:
        return True


def change_password(uid: str, account: str, new_pwd: str) -> bool:
    """修改本地账号密码。

    密码统一存储在 User.password_hash，所有本地登录方式共享同一密码。
    调用前需确保用户已通过 @apilogin_required 等登录态校验。

    :param uid: 用户 UID
    :param account: 本地账号
    :param new_pwd: 新密码（明文）
    :returns: 成功返回 True
    :raises ParamError: 参数校验失败
    :raises AuthError: 密码验证失败或账号不存在
    """
    if not is_local_account(account):
        raise ParamError("Only local accounts can change password")
    if not check_credential_rule(new_pwd):
        raise ParamError("New password must be 6-32 characters")
    try:
        u = User.get(User.uid == uid)
    except User.DoesNotExist:
        raise AuthError("User not found")
    # 校验新旧密码不能相同
    if u.password_hash and check_password_hash(u.password_hash, new_pwd):
        raise ParamError("New password must be different from current password")
    u.password_hash = generate_password_hash(new_pwd)
    u.mtime = now()
    u.save()
    return True


def login(account: str, credential: str) -> bool:
    """验证本地账号密码。

    密码统一从 User.password_hash 读取，所有本地登录方式共享同一密码。
    第三方账号不支持此方法，请走 OAuth 授权流程。

    :param account: 本地账号
    :param credential: 密码凭证
    :returns: 验证通过返回 True，否则 False
    :raises ParamError: 参数无效
    :raises AuthError: 账号不存在或非本地账号
    """
    if not account or not credential or not check_credential_rule(credential):
        raise ParamError("Invalid account or credential")
    if not has_account(account):
        raise AuthError("Not found account")
    a = Auth.get(Auth.account == account)
    if not is_local_account(account):
        raise AuthError("Only local accounts can login via this method")
    try:
        u = User.get(User.uid == a.uid)
    except User.DoesNotExist:
        raise AuthError("User not found")
    if not u.password_hash:
        raise AuthError("Account has no password set")
    return check_password_hash(u.password_hash, credential)


def generate_jwt(account: str, expire: int = 7200, session_key: str = "") -> Union[None, str]:
    """根据账号和凭证生成 JWT token。

    :param account: 用户账号
    :param expire: 过期时间（秒），默认 7200（2 小时）
    :param session_key: 会话标识（可选），用于关联活跃会话记录
    :returns: JWT 字符串，账号不存在时返回 None
    """
    if not has_account(account):
        return
    a = Auth.get(Auth.account == account)
    if a:
        payload = dict(sub=account, uid=a.uid)
        if session_key:
            payload["skey"] = session_key
        return jwt_encode(
            config["SECRET_KEY"],
            payload,
            expire,
        )


def verify_jwt(token: str, dump: bool = False) -> Union[bool, GetItemMixIn]:
    """验证 JWT 并可选返回 payload。

    :param token: JWT token 字符串
    :param dump: 为 True 时验证成功后返回 payload（GetItemMixIn 格式），否则返回 True/False
    :returns: 验证结果（bool 或 GetItemMixIn）
    """
    try:
        unsafe_payload = jwt_decode_payload_without_verify(token)
        if "uid" not in unsafe_payload or "sub" not in unsafe_payload:
            raise ParamError("Invalid payload")
    except (BinasciiError, ParamError, TypeError):
        return False
    else:
        pd = GetItemMixIn(unsafe_payload)
        try:
            a = Auth.get((Auth.uid == pd.uid) & (Auth.account == pd.sub))
        except Auth.DoesNotExist:
            return False
        if a:
            try:
                payload = jwt_decode(token, config["SECRET_KEY"], pd.sub)
            except JWTError:
                return False
            else:
                return GetItemMixIn(payload) if dump is True else True
    return False


def record_login(
    uid: str,
    account: str,
    method: str,
    *,
    ip: str = "",
    location: str = "",
    user_agent: str = "",
    browser: str = "",
    os: str = "",
    device: str = "",
    fingerprint: str = "",
) -> None:
    """写入一条登录历史记录到 LoginRecord 表。

    此函数仅执行数据库写入，不进行任何解析或网络请求。
    调用方应在后台线程中预先计算好 browser/os/device/location/fingerprint。

    :param uid: 用户 uid
    :param account: 登录使用的账号
    :param method: 登录方式（local / oauth2_github / oauth2_gitee / oauth2_qq / oauth2_weibo）
    :param ip: 客户端 IP
    :param location: 地理位置
    :param user_agent: 原始 User-Agent 字符串
    :param browser: 浏览器名称
    :param os: 操作系统
    :param device: 设备类型
    :param fingerprint: 浏览器指纹哈希
    """
    try:
        LoginRecord.create(
            uid=uid,
            account=account,
            method=method,
            ip=ip,
            location=location,
            user_agent=user_agent,
            browser=browser,
            os=os,
            device=device,
            fingerprint=fingerprint,
        )
        logger.info(
            f"Login recorded: uid={uid} method={method} "
            f"browser={browser} os={os} ip={ip} location={location}"
        )
    except Exception as e:
        logger.error(f"Failed to record login: {e}")


def list_login_records(uid: str, limit: int = 10) -> List[dict]:
    """查询用户最近 N 条登录记录。

    :param uid: 用户 uid
    :param limit: 返回条数，默认 10
    :returns: 登录记录列表（dict 格式），按时间倒序
    """
    rows = (
        LoginRecord.select()
        .where(LoginRecord.uid == uid)
        .order_by(LoginRecord.ctime.desc())
        .limit(limit)
    )
    return [model_to_dict(r) for r in rows]


# -------------------------------------------------------------------
# 活跃会话管理
# -------------------------------------------------------------------

def create_session(
    uid: str,
    session_key: str,
    *,
    ip: str = "",
    user_agent: str = "",
    expire_time: int = 0,
    method: str = "",
) -> int:
    """创建一条活跃会话记录。

    :param uid: 用户 uid
    :param session_key: 会话标识符
    :param ip: 客户端 IP
    :param user_agent: 原始 User-Agent 字符串
    :param expire_time: 会话过期时间戳（对应 JWT exp）
    :param method: 登录来源（local/vcode/passkey/oauth2_github 等）
    :returns: 新记录的主键 id
    """
    browser, os_name, device = parse_user_agent(user_agent)
    row = UserSession.create(
        uid=uid,
        session_key=session_key,
        ip=ip,
        user_agent=user_agent,
        browser=browser if browser != "Unknown" else "",
        os=os_name if os_name != "Unknown" else "",
        device=device if device != "Desktop" else "",
        expire_time=expire_time,
        method=method,
    )
    logger.info(f"Session created: uid={uid} skey={session_key[:8]}... method={method}")
    return row.id


def update_session_info(
    session_key: str,
    *,
    location: str = "",
    browser: str = "",
    os: str = "",
    device: str = "",
) -> bool:
    """更新会话的 IP 位置、UA 解析信息（由后台线程调用）。

    :param session_key: 会话标识符
    :returns: 更新成功返回 True
    """
    try:
        update_fields = {}
        if location:
            update_fields[UserSession.location] = location
        if browser:
            update_fields[UserSession.browser] = browser
        if os:
            update_fields[UserSession.os] = os
        if device:
            update_fields[UserSession.device] = device
        if update_fields:
            UserSession.update(**update_fields).where(
                UserSession.session_key == session_key
            ).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to update session {session_key[:8]}: {e}")
        return False


def list_active_sessions(uid: str) -> List[dict]:
    """查询指定用户的所有活跃会话（未过期），按登录时间倒序。

    :param uid: 用户 uid
    :returns: 活跃会话列表（dict 格式）
    """
    rows = (
        UserSession.select()
        .where(
            (UserSession.uid == uid)
            & (UserSession.expire_time > now())
        )
        .order_by(UserSession.ctime.desc())
    )
    return [model_to_dict(r) for r in rows]


def delete_session(session_key: str) -> bool:
    """删除指定会话记录（登出时调用）。

    :param session_key: 会话标识符
    :returns: 删除成功返回 True
    """
    try:
        row = UserSession.get(UserSession.session_key == session_key)
        row.delete_instance()
        return True
    except UserSession.DoesNotExist:
        return False
    except Exception as e:
        logger.error(f"Failed to delete session {session_key[:8]}: {e}")
        return False


def delete_user_sessions(uid: str) -> int:
    """删除指定用户的所有会话记录（注销账号或全设备登出时调用）。

    :param uid: 用户 uid
    :returns: 删除的记录数
    """
    return UserSession.delete().where(UserSession.uid == uid).execute()
