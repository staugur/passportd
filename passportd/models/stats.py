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

后台数据概览统计。

统计口径集中在少数几条聚合查询中，结果以 JSON 形式缓存 60 秒，
避免概览页每次刷新都做大范围聚合。按天分桶在 Python 端完成，
以兼容 SQLite / MySQL / PostgreSQL 的日期函数差异。
"""

import json
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any, Dict, List, Optional

from peewee import fn

from .audit import ACTION_LABELS
from .model import (
    AuditLog,
    Auth,
    LoginRecord,
    OAuthAuthorization,
    OAuthClient,
    PasskeyCredential,
    User,
    UserSession,
)
from ..basis.common import now
from ..basis.vars import PROC_NAME
from ..utils.common import logger, rdb

#: 概览数据缓存键
STATS_CACHE_KEY = f"{PROC_NAME}:admin:stats"
#: 概览数据缓存时长（秒）
STATS_CACHE_TTL = 60
#: 趋势图覆盖天数
TREND_DAYS = 30
#: 近 7 天活跃用户窗口（秒）
ACTIVE_WINDOW = 7 * 86400
#: 单账号近 24 小时登录 IP 数达到该值视为异常
SUSPICIOUS_IP_LIMIT = 3


def _day_start(offset_days: int = 0) -> int:
    """返回本地时间 N 天前零点的 Unix 时间戳。"""
    day = date.today() - timedelta(days=offset_days)
    return int(datetime.combine(day, dt_time.min).timestamp())


def _count_by_day(
    timestamps: List[int], start_ts: int, days: int
) -> List[Dict[str, Any]]:
    """将时间戳按本地日期分桶，返回连续 days 天的计数序列。"""
    buckets: Dict[str, int] = {}
    for i in range(days):
        day = (datetime.fromtimestamp(start_ts).date() + timedelta(days=i))
        buckets[day.isoformat()] = 0
    for ts in timestamps:
        if not ts:
            continue
        key = date.fromtimestamp(int(ts)).isoformat()
        if key in buckets:
            buckets[key] += 1
    return [{"date": k, "count": v} for k, v in buckets.items()]


def _group_counts(query) -> List[Dict[str, Any]]:
    """将 (name, count) 查询结果转为字典列表。"""
    return [
        {"name": row[0] or "", "count": int(row[1] or 0)} for row in query
    ]


def _suspicious_accounts(since_ts: int) -> List[Dict[str, Any]]:
    """找出近 24 小时登录 IP 数异常多的账号。"""
    rows = (
        LoginRecord.select(LoginRecord.uid, LoginRecord.ip)
        .where(LoginRecord.ctime >= since_ts)
        .tuples()
    )
    ip_map: Dict[str, set] = {}
    for uid, ip in rows:
        if not ip or ip == "-":
            continue
        ip_map.setdefault(uid, set()).add(ip)
    flagged = [
        (uid, len(ips))
        for uid, ips in ip_map.items()
        if len(ips) >= SUSPICIOUS_IP_LIMIT
    ]
    flagged.sort(key=lambda x: x[1], reverse=True)
    flagged = flagged[:5]
    if not flagged:
        return []
    nicknames: Dict[str, str] = {}
    for u in User.select(User.uid, User.nickname).where(
        User.uid.in_([uid for uid, _ in flagged])
    ):
        nicknames[u.uid] = u.nickname
    return [
        {
            "uid": uid,
            "nickname": nicknames.get(uid, ""),
            "ip_count": count,
        }
        for uid, count in flagged
    ]


def build_admin_stats() -> Dict[str, Any]:
    """实时计算后台概览数据（不走缓存）。"""
    ts_now = now()
    week_ago = ts_now - ACTIVE_WINDOW
    day_ago = ts_now - 86400
    trend_start = _day_start(TREND_DAYS - 1)

    kpi = {
        "total_users": User.select().count(),
        "disabled_users": User.select().where(User.status == 0).count(),
        "active_users_7d": (
            LoginRecord.select(
                fn.COUNT(fn.DISTINCT(LoginRecord.uid))
            )
            .where(LoginRecord.ctime >= week_ago)
            .scalar()
            or 0
        ),
        "logins_24h": LoginRecord.select()
        .where(LoginRecord.ctime >= day_ago)
        .count(),
        "active_sessions": UserSession.select()
        .where(UserSession.expire_time > ts_now)
        .count(),
        "oauth_clients": OAuthClient.select().count(),
        "internal_clients": OAuthClient.select()
        .where(OAuthClient.is_internal)
        .count(),
        "oauth_authorizations": OAuthAuthorization.select().count(),
        "passkey_users": (
            PasskeyCredential.select(
                fn.COUNT(fn.DISTINCT(PasskeyCredential.uid))
            ).scalar()
            or 0
        ),
    }

    register_trend = _count_by_day(
        [
            row[0]
            for row in User.select(User.ctime)
            .where(User.ctime >= trend_start)
            .tuples()
        ],
        trend_start,
        TREND_DAYS,
    )
    login_trend = _count_by_day(
        [
            row[0]
            for row in LoginRecord.select(LoginRecord.ctime)
            .where(LoginRecord.ctime >= trend_start)
            .tuples()
        ],
        trend_start,
        TREND_DAYS,
    )

    method_dist = _group_counts(
        LoginRecord.select(
            LoginRecord.method, fn.COUNT().alias("count")
        )
        .where(LoginRecord.ctime >= trend_start)
        .group_by(LoginRecord.method)
        .order_by(fn.COUNT().desc())
        .tuples()
    )
    classify_dist = _group_counts(
        Auth.select(Auth.classify, fn.COUNT().alias("count"))
        .group_by(Auth.classify)
        .order_by(fn.COUNT().desc())
        .tuples()
    )
    location_top = _group_counts(
        LoginRecord.select(
            LoginRecord.location, fn.COUNT().alias("count")
        )
        .where(
            (LoginRecord.ctime >= trend_start)
            & (LoginRecord.location != "")
        )
        .group_by(LoginRecord.location)
        .order_by(fn.COUNT().desc())
        .limit(8)
        .tuples()
    )

    admin_actions = []
    for row in (
        AuditLog.select()
        .where(AuditLog.action.startswith("admin_"))
        .order_by(AuditLog.ctime.desc())
        .limit(8)
    ):
        admin_actions.append(
            {
                "uid": row.uid,
                "action": row.action,
                "action_label": ACTION_LABELS.get(row.action, row.action),
                "ctime": row.ctime,
                "ip": row.ip,
            }
        )

    return {
        "kpi": kpi,
        "register_trend": register_trend,
        "login_trend": login_trend,
        "method_dist": method_dist,
        "classify_dist": classify_dist,
        "location_top": location_top,
        "admin_actions": admin_actions,
        "suspicious": _suspicious_accounts(day_ago),
        "generated_at": ts_now,
    }


def get_admin_stats(use_cache: bool = True) -> Dict[str, Any]:
    """获取后台概览数据，优先读取 Redis 缓存。

    :param use_cache: False 时强制实时计算并刷新缓存
    :returns: 概览数据字典
    """
    if use_cache:
        try:
            cached: Optional[bytes] = rdb.get(STATS_CACHE_KEY)
            if cached:
                return json.loads(cached)
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取后台概览缓存失败: %s", exc)

    stats = build_admin_stats()
    try:
        rdb.setex(
            STATS_CACHE_KEY,
            STATS_CACHE_TTL,
            json.dumps(stats, ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("写入后台概览缓存失败: %s", exc)
    return stats
