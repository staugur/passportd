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
from typing import Any, Dict, List

from playhouse.shortcuts import model_to_dict

from .model import AuditLog
from ..basis.common import now
from ..utils.common import logger

# 操作类型中文映射
ACTION_LABELS: Dict[str, str] = {
    "register": "注册",
    "bind_account": "绑定账号",
    "unbind_account": "解绑账号",
    "passkey_add": "添加 Passkey",
    "passkey_delete": "删除 Passkey",
    "oidc_client_create": "创建 OIDC 客户端",
    "oidc_client_update": "修改 OIDC 客户端",
    "oidc_client_delete": "删除 OIDC 客户端",
    "oidc_auth_revoke": "撤销 OIDC 授权",
    "change_password": "修改密码",
    "account_delete": "注销账号",
    "role_set": "设置角色",
    "role_add": "添加角色",
    "role_remove": "移除角色",
}


def record_audit_log(
    uid: str,
    action: str,
    detail: Dict[str, Any],
    ip: str = "",
    user_agent: str = "",
) -> bool:
    """写入一条审计日志记录。

    :param uid: 用户唯一标识符
    :param action: 操作类型，取值见 ``ACTION_LABELS`` 的 key
    :param detail: 操作详情字典，将被序列化为 JSON 字符串存储
    :param ip: 客户端 IP
    :param user_agent: User-Agent 字符串
    :returns: 写入成功返回 True
    """
    try:
        AuditLog.create(
            uid=uid,
            action=action,
            detail=json.dumps(detail, ensure_ascii=False),
            ip=ip,
            user_agent=user_agent,
            ctime=now(),
        )
        logger.info(f"Audit log recorded: uid={uid} action={action} detail={detail}")
        return True
    except Exception as e:
        logger.error(f"Failed to record audit log: {e}")
        return False


def list_audit_logs(
    uid: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """查询用户的审计日志记录，按时间倒序排列。

    :param uid: 用户唯一标识符
    :param limit: 返回条数，默认 50
    :param offset: 偏移量，默认 0
    :returns: 审计日志记录列表（dict 格式，detail 已反序列化）
    """
    rows = (
        AuditLog.select()
        .where(AuditLog.uid == uid)
        .order_by(AuditLog.ctime.desc())
        .offset(offset)
        .limit(limit)
    )
    result = []
    for r in rows:
        item = model_to_dict(r)
        # 反序列化 detail 字段
        try:
            item["detail"] = json.loads(item["detail"]) if item["detail"] else {}
        except (json.JSONDecodeError, TypeError):
            item["detail"] = {}
        # 添加中文标签
        item["action_label"] = ACTION_LABELS.get(item["action"], item["action"])
        result.append(item)
    return result


def clear_user_audit_logs(uid: str) -> int:
    """清除用户的所有审计日志。

    注意：注销账号时审计日志会被保留（含 account_delete 记录），
    此函数仅在需要手动清理时使用。

    :param uid: 用户唯一标识符
    :returns: 删除的记录数
    """
    return AuditLog.delete().where(AuditLog.uid == uid).execute()
