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

from typing import Union, List

from playhouse.shortcuts import model_to_dict
from werkzeug.security import gen_salt

from .model import OAuthClient, OAuthToken, OAuthAuthorization
from ..basis.vars import COMMON_DICT_TYPE
from ..basis.errors import ParamError, DBError
from ..basis.common import check_uid_rule
from ..utils.common import (
    now,
    appname_check,
    is_valid_http_url,
    is_valid_ipv4,
)


def has_oauth_client(name: str) -> bool:
    """判断OAuthClient存在"""
    return OAuthClient.select().where(OAuthClient.name == name).exists()


def list_oauth_clients(uid: Union[None, str]) -> List[COMMON_DICT_TYPE]:
    """根据 uid 获取用户所有 OIDC Client 信息"""
    if uid and check_uid_rule(uid):
        obj = OAuthClient.select().where(OAuthClient.uid == uid)
    else:
        obj = OAuthClient.select()
    return [model_to_dict(u) for u in obj]


def get_oauth_client(client_id: str) -> Union[None, COMMON_DICT_TYPE]:
    """根据 client_id 获取应用信息"""
    try:
        oc = OAuthClient.get(OAuthClient.client_id == client_id)
        return model_to_dict(oc)
    except OAuthClient.DoesNotExist:
        return None


def list_oauth_tokens(uid: str, client_id: Union[None, str]) -> List[COMMON_DICT_TYPE]:
    """根据 uid 获取用户所有 OIDC Token 信息"""
    if isinstance(client_id, str) and len(client_id) >= 24:
        obj = OAuthToken.select().where(
            (OAuthToken.uid == uid) & (OAuthToken.client_id == client_id)
        )
    else:
        obj = OAuthToken.select().where(OAuthToken.uid == uid)
    return [model_to_dict(u) for u in obj]


def get_oauth_token(access_token: str) -> Union[None, COMMON_DICT_TYPE]:
    """根据 access_token 获取 Token 信息"""
    try:
        ot = OAuthToken.get(OAuthToken.access_token == access_token)
        return model_to_dict(ot)
    except OAuthToken.DoesNotExist:
        return None


def create_oauth_client(
    uid: str,
    name: str,
    redirect_uri: str,
    *,
    scope: str = "openid",
    homepage: str = "",
    bio: str = "",
) -> COMMON_DICT_TYPE:
    """
    注册一个 OIDC (OpenID Connect) 客户端应用。

    Args:
        uid (str): 用户唯一标识符，长度为 22 个字符。
        name (str): 客户端应用的名称，需通过 `appname_check` 验证。
        redirect_uri (str): 有效的 HTTP URL，用于 OAuth 回调。
        scope (str, optional): 授权范围，默认为 "openid"。
        homepage (str, optional): 客户端应用的主页 URL，需为有效的 HTTP URL。
        bio (str, optional): 客户端应用的描述信息。

    Returns:
        COMMON_DICT_TYPE: 包含生成的 `client_id` 和 `client_secret` 的字典。

    Raises:
        ParamError: 如果参数验证失败（如 `uid` 长度、`name` 格式、`redirect_uri` 或 `homepage` 无效）。
        DBError: 如果数据库操作失败。
        ParamError: 如果客户端名称已存在。

    Notes:
        - 客户端 ID 和密钥通过 `gen_salt` 生成。
        - 默认授权类型为 "authorization_code"，响应类型为 "code"。
    """
    if (
        len(uid) == 22
        and appname_check(name)
        and is_valid_http_url(redirect_uri)
        and "openid" in scope
    ):
        pass
    else:
        raise ParamError("Invalid params")
    if homepage:
        if not is_valid_http_url(homepage):
            raise ParamError("Invalid homepage")
    ctime = now()
    if has_oauth_client(name):
        raise ParamError("The client name already exists")
    try:
        client_id = gen_salt(24)
        client_secret = gen_salt(48)
        OAuthClient.create(
            uid=uid,
            name=name,
            homepage=homepage,
            bio=bio,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            grant_type="authorization_code",
            response_type="code",
            scope=scope,
            ctime=ctime,
        )
    except Exception as e:
        raise DBError(e)
    else:
        return dict(
            client_id=client_id,
            client_secret=client_secret,
        )


def update_oauth_client(
    uid: str,
    client_id: str,
    *,
    name: str = "",
    bio: str = "",
    homepage: str = "",
    redirect_uri: str = "",
    scope: str = "",
) -> COMMON_DICT_TYPE:
    """
    更新 OIDC 客户端应用信息。

    Args:
        uid (str): 用户唯一标识符，用于校验归属权限。
        client_id (str): 要更新的客户端标识。
        name (str, optional): 新的客户端名称。
        bio (str, optional): 新的描述信息。
        homepage (str, optional): 新的主页 URL。
        redirect_uri (str, optional): 新的回调 URL。
        scope (str, optional): 新的授权范围。

    Returns:
        COMMON_DICT_TYPE: 更新后的客户端信息字典。

    Raises:
        ParamError: 参数验证失败或客户端不存在。
        DBError: 数据库操作失败。
        PermissionError: 无权更新该客户端。
    """
    if not uid or len(uid) != 22 or not client_id or len(client_id) < 24:
        raise ParamError("Invalid params")
    try:
        oc = OAuthClient.get(
            (OAuthClient.client_id == client_id) & (OAuthClient.uid == uid)
        )
    except OAuthClient.DoesNotExist:
        raise PermissionError("Client not found or permission denied")
    if name:
        if not appname_check(name):
            raise ParamError("Invalid name")
        if name != oc.name and has_oauth_client(name):
            raise ParamError("The client name already exists")
        oc.name = name
    if bio:
        oc.bio = bio
    if homepage:
        if not is_valid_http_url(homepage):
            raise ParamError("Invalid homepage")
        oc.homepage = homepage
    if redirect_uri:
        if not is_valid_http_url(redirect_uri):
            raise ParamError("Invalid redirect_uri")
        oc.redirect_uri = redirect_uri
    if scope:
        if "openid" not in scope:
            raise ParamError("scope must contain openid")
        oc.scope = scope
    oc.mtime = now()
    try:
        oc.save()
    except Exception as e:
        raise DBError(e)
    else:
        return model_to_dict(oc)


def delete_oauth_client(uid: str, client_id: str) -> bool:
    """
    删除 OIDC 客户端应用。

    Args:
        uid (str): 用户唯一标识符，用于校验归属权限。
        client_id (str): 要删除的客户端标识。

    Returns:
        bool: 删除成功返回 True。

    Raises:
        PermissionError: 客户端不存在或无权删除。
        DBError: 数据库操作失败。
    """
    if not uid or len(uid) != 22 or not client_id or len(client_id) < 24:
        raise ParamError("Invalid params")
    try:
        oc = OAuthClient.get(
            (OAuthClient.client_id == client_id) & (OAuthClient.uid == uid)
        )
    except OAuthClient.DoesNotExist:
        raise PermissionError("Client not found or permission denied")
    try:
        # 同时删除关联的 Token
        OAuthToken.delete().where(OAuthToken.client_id == client_id).execute()
        oc.delete_instance()
    except Exception as e:
        raise DBError(e)
    else:
        return True


def list_oauth_authorizations_by_user(uid: str) -> List[COMMON_DICT_TYPE]:
    """获取用户所有 OIDC 授权记录（含客户端名称等信息）。

    :param uid: 用户唯一标识符
    :returns: 授权记录列表，每条包含 client_id, scope, created_at, client_name, homepage, bio
    """
    if not uid or len(uid) != 22:
        return []
    oa = OAuthAuthorization.alias()
    oc = OAuthClient.alias()
    records = (
        OAuthAuthorization
        .select(
            OAuthAuthorization.client_id,
            OAuthAuthorization.scope,
            OAuthAuthorization.created_at,
            OAuthAuthorization.ip,
            OAuthAuthorization.ua,
            OAuthClient.name,
            OAuthClient.homepage,
            OAuthClient.bio,
        )
        .join(OAuthClient, on=(OAuthAuthorization.client_id == OAuthClient.client_id))
        .where(OAuthAuthorization.uid == uid)
        .order_by(OAuthAuthorization.created_at.desc())
    )
    return [model_to_dict(r) for r in records]


def delete_oauth_authorization(uid: str, client_id: str) -> int:
    """撤销用户对某个 OIDC 客户端的授权，同时删除关联的 Token。

    :param uid: 用户唯一标识符
    :param client_id: 客户端标识
    :returns: 删除的授权记录数
    :raises PermissionError: 授权记录不存在
    """
    if not uid or len(uid) != 22 or not client_id or len(client_id) < 24:
        raise ParamError("Invalid params")
    # 先删 Token
    OAuthToken.delete().where(
        (OAuthToken.client_id == client_id) & (OAuthToken.uid == uid)
    ).execute()
    # 再删授权记录
    result = (
        OAuthAuthorization
        .delete()
        .where(
            (OAuthAuthorization.client_id == client_id)
            & (OAuthAuthorization.uid == uid)
        )
        .execute()
    )
    if result == 0:
        raise PermissionError("Authorization not found")
    return result


def count_oauth_authorizations(client_id: str) -> int:
    """
    统计某个 OIDC 客户端被多少不同用户授权过（表中仅记录 approved）。

    Args:
        client_id (str): 客户端标识。

    Returns:
        int: 授权用户数（去重）。
    """
    if not client_id or len(client_id) < 24:
        return 0
    return (
        OAuthAuthorization
        .select(OAuthAuthorization.uid)
        .where(OAuthAuthorization.client_id == client_id)
        .distinct()
        .count()
    )


def save_oauth_token(
    uid: str,
    client_id: str,
    access_token: str,
    expires_in: int,
    scope: str,
    *,
    ip: str = "",
    ua: str = "",
) -> bool:
    """保存 OIDC Token 到数据库。

    :param uid: 用户唯一标识符（22 位）
    :param client_id: OIDC 客户端标识
    :param access_token: 访问令牌字符串
    :param expires_in: 过期时间（秒）
    :param scope: 授权范围（空格分隔）
    :param ip: 客户端 IP 地址
    :param ua: 客户端 User-Agent
    :returns: 保存成功返回 True
    :raises ParamError: 参数校验失败
    :raises DBError: 数据库操作失败
    """
    if (
        len(uid) == 22
        and len(client_id) >= 24
        and access_token
        and isinstance(expires_in, int)
        and "openid" in scope
    ):
        pass
    else:
        raise ParamError("Invalid params")
    if ip:
        if not is_valid_ipv4(ip):
            raise ParamError("Invalid ip")
    ctime = now()
    try:
        OAuthToken.create(
            uid=uid,
            client_id=client_id,
            token_type="Bearer",
            access_token=access_token,
            expires_in=expires_in,
            scope=scope,
            ctime=ctime,
            status=1,
            ip=ip,
            ua=ua,
        )
    except Exception as e:
        raise DBError(e)
    else:
        return True


def save_oauth_authorization(
    uid: str,
    client_id: str,
    scope: str,
    *,
    ip: str = "",
    ua: str = "",
) -> bool:
    """
    保存 OIDC 用户授权记录（仅 approved）。

    Args:
        uid (str): 授权用户的唯一标识符，长度为 22 个字符。
        client_id (str): 被授权的 OIDC 客户端标识。
        scope (str): 授权的 scope 范围（空格分隔）。
        ip (str, optional): 客户端 IP 地址。
        ua (str, optional): 客户端 User-Agent。

    Returns:
        bool: 保存成功返回 True。

    Raises:
        ParamError: 如果参数验证失败。
        DBError: 如果数据库操作失败。
    """
    if len(uid) != 22 or len(client_id) < 24 or not scope:
        raise ParamError("Invalid params")
    if ip and not is_valid_ipv4(ip):
        raise ParamError("Invalid ip")
    ctime = now()
    try:
        OAuthAuthorization.create(
            uid=uid,
            client_id=client_id,
            scope=scope,
            ctime=ctime,
            ip=ip,
            ua=ua,
        )
    except Exception as e:
        raise DBError(e)
    else:
        return True
