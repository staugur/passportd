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

from typing import Dict, List, Tuple, Union, Optional

from playhouse.shortcuts import model_to_dict
from werkzeug.security import gen_salt

from .model import OAuthClient, OAuthToken, OAuthAuthorization, User, db
from ..basis.vars import COMMON_DICT_TYPE, MAX_REDIRECT_URIS
from ..basis.errors import ParamError, DBError
from ..basis.common import check_uid_rule
from ..utils.common import (
    now,
    appname_check,
    is_valid_http_url,
    is_valid_ipv4,
    logger,
    parse_redirect_uris,
)


def has_oauth_client(name: str) -> bool:
    """判断指定名称的 OAuth Client 是否已存在。

    :param name: 客户端应用名称
    :returns: 存在返回 True，否则 False
    """
    return OAuthClient.select().where(OAuthClient.name == name).exists()


def list_oauth_clients(uid: Union[None, str]) -> List[COMMON_DICT_TYPE]:
    """根据 uid 获取用户所有 OIDC Client 信息。

    :param uid: 用户唯一标识符；为 None 或非法时返回全部客户端
    :returns: 客户端信息字典列表
    """
    if uid and check_uid_rule(uid):
        obj = OAuthClient.select().where(OAuthClient.uid == uid)
    else:
        obj = OAuthClient.select()
    clients = [model_to_dict(u) for u in obj]
    for c in clients:
        c["redirect_uris"] = _collect_redirect_uris(c)
    return clients


def _collect_redirect_uris(d: COMMON_DICT_TYPE) -> List[str]:
    """从客户端字典（含 redirect_uri..redirect_uri5 字段）提取非空回调地址列表。

    :param d: 客户端信息字典
    :returns: 非空回调地址列表（按字段顺序排列）
    """
    uris: List[str] = []
    for i in range(1, MAX_REDIRECT_URIS + 1):
        key = "redirect_uri" if i == 1 else "redirect_uri{}".format(i)
        val = d.get(key)
        if val:
            uris.append(val)
    return uris


def _spread_redirect_uris(uris: List[str]) -> Tuple[str, str, str, str, str]:
    """将回调地址列表铺开为 5 个字段值（不足补空字符串）。

    :param uris: 已规范化、去重的回调地址列表（长度 1~5）
    :returns: 对应 5 个字段值的元组
    """
    padded = list(uris) + [""] * (MAX_REDIRECT_URIS - len(uris))
    return padded[0], padded[1], padded[2], padded[3], padded[4]


def get_oauth_client(client_id: str) -> Union[None, COMMON_DICT_TYPE]:
    """根据 client_id 获取应用信息。

    :param client_id: 客户端标识
    :returns: 客户端信息字典（含 ``redirect_uris`` 白名单列表），不存在返回 None
    """
    try:
        oc = OAuthClient.get(OAuthClient.client_id == client_id)
    except OAuthClient.DoesNotExist:
        return None
    info = model_to_dict(oc)
    info["redirect_uris"] = _collect_redirect_uris(info)
    return info


def is_internal_oauth_client(name: str) -> bool:
    """判断同名客户端是否被标记为内部（自家）应用。

    内部应用标记存储在 ``OAuthClient.is_internal``，由后台管理页面维护，
    与配置项 ``OIDC_INTERNAL_CLIENTS`` 等效。

    :param name: 客户端应用名称
    :returns: 是内部应用返回 True，否则 False
    """
    if not name:
        return False
    try:
        return (
            OAuthClient.select()
            .where(
                (OAuthClient.name == name)
                & (OAuthClient.is_internal == True)  # noqa: E712
            )
            .exists()
        )
    except Exception as e:  # noqa: BLE001
        # 数据库不可用或表未初始化时按「非内部应用」处理，不阻断授权流程
        logger.debug("is_internal_oauth_client 查询失败: %s", e)
        return False


def list_internal_client_names() -> List[str]:
    """列出所有被标记为内部（自家）应用的客户端名称。

    :returns: 客户端名称列表，查询失败时返回空列表
    """
    try:
        return [
            c.name
            for c in OAuthClient.select(OAuthClient.name).where(
                OAuthClient.is_internal == True  # noqa: E712
            )
        ]
    except Exception as e:  # noqa: BLE001
        logger.debug("list_internal_client_names 查询失败: %s", e)
        return []


def list_oauth_tokens(uid: str, client_id: Union[None, str]) -> List[COMMON_DICT_TYPE]:
    """根据 uid 获取用户所有 OIDC Token 信息。

    :param uid: 用户唯一标识符
    :param client_id: 客户端标识，为空或非法时返回该用户全部 Token
    :returns: Token 信息字典列表
    """
    if isinstance(client_id, str) and len(client_id) >= 24:
        obj = OAuthToken.select().where(
            (OAuthToken.uid == uid) & (OAuthToken.client_id == client_id)
        )
    else:
        obj = OAuthToken.select().where(OAuthToken.uid == uid)
    return [model_to_dict(u) for u in obj]


def get_oauth_token(access_token: str) -> Union[None, COMMON_DICT_TYPE]:
    """根据 access_token 获取 Token 信息。

    :param access_token: 访问令牌字符串
    :returns: Token 信息字典，不存在返回 None
    """
    try:
        ot = OAuthToken.get(OAuthToken.access_token == access_token)
        return model_to_dict(ot)
    except OAuthToken.DoesNotExist:
        return None


def create_oauth_client(
    uid: str,
    name: str,
    redirect_uris: List[str],
    *,
    scope: str = "openid",
    homepage: str = "",
    bio: str = "",
) -> COMMON_DICT_TYPE:
    """注册一个 OIDC (OpenID Connect) 客户端应用。

    客户端 ID 和密钥通过 ``gen_salt`` 生成，默认授权类型为
    ``authorization_code``，响应类型为 ``code``。

    :param uid: 用户唯一标识符，长度为 22 个字符
    :param name: 客户端应用名称，需通过 ``appname_check`` 验证
    :param redirect_uris: 回调地址列表（1~5 个，仅取 scheme://host[:port][/path]）
    :param scope: 授权范围，默认为 ``openid``
    :param homepage: 客户端应用的主页 URL，需为有效的 HTTP URL
    :param bio: 客户端应用的描述信息
    :returns: 包含生成的 ``client_id`` 和 ``client_secret`` 的字典
    :raises ParamError: 参数验证失败或客户端名称已存在
    :raises DBError: 数据库操作失败
    """
    if len(uid) == 22 and appname_check(name) and "openid" in scope:
        pass
    else:
        raise ParamError("Invalid params")
    # 解析并规范化回调地址列表（校验数量与格式，剥离查询参数与片段）
    uris = parse_redirect_uris(redirect_uris)
    if homepage:
        if not is_valid_http_url(homepage):
            raise ParamError("Invalid homepage")
    ctime = now()
    if has_oauth_client(name):
        raise ParamError("The client name already exists")
    r1, r2, r3, r4, r5 = _spread_redirect_uris(uris)
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
            redirect_uri=r1,
            redirect_uri2=r2,
            redirect_uri3=r3,
            redirect_uri4=r4,
            redirect_uri5=r5,
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
    redirect_uris: Optional[List[str]] = None,
    scope: str = "",
) -> COMMON_DICT_TYPE:
    """更新 OIDC 客户端应用信息。

    :param uid: 用户唯一标识符，用于校验归属权限
    :param client_id: 要更新的客户端标识
    :param name: 新的客户端名称
    :param bio: 新的描述信息
    :param homepage: 新的主页 URL
    :param redirect_uri: 新的回调 URL
    :param scope: 新的授权范围
    :returns: 更新后的客户端信息字典
    :raises ParamError: 参数验证失败
    :raises PermissionError: 客户端不存在或无权更新
    :raises DBError: 数据库操作失败
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
    if redirect_uris is not None:
        uris = parse_redirect_uris(redirect_uris)
        r1, r2, r3, r4, r5 = _spread_redirect_uris(uris)
        oc.redirect_uri = r1
        oc.redirect_uri2 = r2
        oc.redirect_uri3 = r3
        oc.redirect_uri4 = r4
        oc.redirect_uri5 = r5
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
        ret = model_to_dict(oc)
        ret["redirect_uris"] = _collect_redirect_uris(ret)
        return ret


def delete_oauth_client(uid: str, client_id: str) -> bool:
    """删除 OIDC 客户端应用，同时删除关联的 Token。

    :param uid: 用户唯一标识符，用于校验归属权限
    :param client_id: 要删除的客户端标识
    :returns: 删除成功返回 True
    :raises ParamError: 参数校验失败
    :raises PermissionError: 客户端不存在或无权删除
    :raises DBError: 数据库操作失败
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


def list_oauth_authorizations_by_user(
    uid: str, limit: int = 0
) -> List[COMMON_DICT_TYPE]:
    """获取用户所有 OIDC 授权记录（含客户端名称等信息）。

    :param uid: 用户唯一标识符
    :param limit: 返回记录数上限，0 表示不限制
    :returns: 授权记录列表，每条包含 client_id, scope, ctime, name, homepage, bio
    """
    if not uid or len(uid) != 22:
        return []
    records = (
        OAuthAuthorization.select(
            OAuthAuthorization.client_id,
            OAuthAuthorization.scope,
            OAuthAuthorization.ctime,
            OAuthAuthorization.ip,
            OAuthAuthorization.ua,
            OAuthClient.name,
            OAuthClient.homepage,
            OAuthClient.bio,
        )
        .join(OAuthClient, on=(OAuthAuthorization.client_id == OAuthClient.client_id))
        .where(OAuthAuthorization.uid == uid)
        .order_by(OAuthAuthorization.ctime.desc())
        .dicts()
    )
    if limit > 0:
        records = records.limit(limit)
    return list(records)


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
        OAuthAuthorization.delete()
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
    """统计某个 OIDC 客户端被多少不同用户授权过（表中仅记录 approved）。

    :param client_id: 客户端标识
    :returns: 授权用户数（去重）
    """
    if not client_id or len(client_id) < 24:
        return 0
    return (
        OAuthAuthorization.select(OAuthAuthorization.uid)
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
    """保存 OIDC 用户授权记录（仅 approved）。

    :param uid: 授权用户的唯一标识符，长度为 22 个字符
    :param client_id: 被授权的 OIDC 客户端标识
    :param scope: 授权的 scope 范围（空格分隔）
    :param ip: 客户端 IP 地址
    :param ua: 客户端 User-Agent
    :returns: 保存成功返回 True
    :raises ParamError: 参数校验失败
    :raises DBError: 数据库操作失败
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


def list_oauth_clients_page(
    keyword: str = "",
    page: int = 1,
    per_page: int = 20,
    is_internal: Optional[bool] = None,
    has_role: bool = False,
) -> Tuple[List[COMMON_DICT_TYPE], int]:
    """管理员分页查询所有 OIDC 客户端（含所有者昵称与授权用户数）。

    :param keyword: 搜索关键词，匹配应用名称或所有者（uid / 昵称）
    :param page: 页码，从 1 开始
    :param per_page: 每页条数，最大 100
    :param is_internal: 内部应用筛选，None 表示不筛选
    :param has_role: 为 True 时仅返回授权范围包含 role 的客户端
    :returns: (客户端信息列表, 总条数) 元组
    """
    query = OAuthClient.select()
    if keyword:
        cond = OAuthClient.name.contains(keyword)
        matched_uids = [
            u.uid
            for u in User.select(User.uid).where(
                (User.uid == keyword) | (User.nickname.contains(keyword))
            )
        ]
        if matched_uids:
            cond = cond | (OAuthClient.uid.in_(matched_uids))
        query = query.where(cond)
    if is_internal is not None:
        query = query.where(OAuthClient.is_internal == bool(is_internal))
    if has_role:
        query = query.where(OAuthClient.scope.contains("role"))
    total = query.count()
    page = max(1, page)
    per_page = max(1, min(per_page, 100))
    rows = query.order_by(OAuthClient.ctime.desc()).paginate(page, per_page)
    clients = [model_to_dict(c) for c in rows]
    for c in clients:
        c["redirect_uris"] = _collect_redirect_uris(c)
    uids = {c["uid"] for c in clients}
    owners: Dict[str, str] = {}
    if uids:
        for u in User.select().where(User.uid.in_(uids)):
            owners[u.uid] = u.nickname
    for c in clients:
        c["owner_nickname"] = owners.get(c["uid"], "")
        c["auth_count"] = count_oauth_authorizations(str(c["client_id"]))
    return clients, total


def admin_set_client_internal(
    client_id: str, is_internal: bool
) -> COMMON_DICT_TYPE:
    """管理员标记任意 OIDC 客户端是否为内部（自家）应用。

    内部应用在申请 ``role`` scope 时可获得用户平台角色，等效于配置项
    ``OIDC_INTERNAL_CLIENTS``。不做归属校验。

    :param client_id: 要标记的客户端标识
    :param is_internal: True 标记为内部应用，False 取消标记
    :returns: 更新后的客户端信息字典
    :raises ParamError: 参数校验失败
    :raises PermissionError: 客户端不存在
    :raises DBError: 数据库操作失败
    """
    if not client_id or len(client_id) < 24:
        raise ParamError("Invalid params")
    try:
        oc = OAuthClient.get(OAuthClient.client_id == client_id)
    except OAuthClient.DoesNotExist:
        raise PermissionError("Client not found")
    oc.is_internal = bool(is_internal)
    oc.mtime = now()
    try:
        oc.save()
    except Exception as e:
        raise DBError(e)
    else:
        return model_to_dict(oc)


def admin_get_oauth_client(client_id: str) -> Optional[COMMON_DICT_TYPE]:
    """管理员查看任意 OIDC 客户端的只读详情。

    :param client_id: 客户端标识
    :returns: 客户端详情字典，不存在时返回 None
    """
    if not client_id or len(client_id) < 24:
        return None
    oc = OAuthClient.get_or_none(OAuthClient.client_id == client_id)
    if not oc:
        return None
    item = model_to_dict(oc)
    item["redirect_uris"] = _collect_redirect_uris(item)
    owner = User.get_or_none(User.uid == oc.uid)
    item["owner_nickname"] = owner.nickname if owner else ""
    item["auth_count"] = count_oauth_authorizations(client_id)
    item["token_count"] = (
        OAuthToken.select().where(OAuthToken.client_id == client_id).count()
    )
    return item


def admin_delete_oauth_client(client_id: str) -> bool:
    """管理员删除任意 OIDC 客户端（不校验归属）。

    同时清理该客户端的令牌与授权记录，避免残留数据。

    :param client_id: 客户端标识
    :returns: 删除成功返回 True
    :raises ParamError: 参数校验失败
    :raises PermissionError: 客户端不存在
    :raises DBError: 数据库操作失败
    """
    if not client_id or len(client_id) < 24:
        raise ParamError("Invalid params")
    try:
        oc = OAuthClient.get(OAuthClient.client_id == client_id)
    except OAuthClient.DoesNotExist:
        raise PermissionError("Client not found")
    try:
        with db.atomic():
            OAuthToken.delete().where(
                OAuthToken.client_id == client_id
            ).execute()
            OAuthAuthorization.delete().where(
                OAuthAuthorization.client_id == client_id
            ).execute()
            oc.delete_instance()
    except Exception as e:
        raise DBError(e)
    else:
        return True
