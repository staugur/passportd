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

from sys import version_info
from os import getenv, makedirs
from os.path import join, exists
from typing import Any, Optional, Union, List
from time import time, mktime
from datetime import timedelta, datetime

from .vars import ENV_PREFIX, ApiRespType, COMMON_DICT_TYPE, APP_DIR


def new_res(
    success: bool = False,
    data: Union[COMMON_DICT_TYPE, List[COMMON_DICT_TYPE], str] = "",
) -> ApiRespType:
    """构造统一 API 响应结构。

    :param success: 请求是否成功
    :param data: 响应数据，可选
    :returns: 标准 API 响应字典 ``{"success": bool, "message": str, "data": ...}``
    """
    res = ApiRespType(success=success, message="")
    if data:
        res.update(data=data)
    return res


def is_true(value: Any) -> bool:
    """判断一个值是否为“真”（支持 str / int / bool 形式）。

    :param value: 任意待判断的值
    :returns: 值为真返回 True，否则返回 False
    """
    if value and value in (True, "True", "true", "on", 1, "1", "yes"):
        return True
    return False


def raise_version():
    """检查 Python 版本，低于 3.10 时抛出 RuntimeError。"""
    vs = version_info
    if (vs[0], vs[1]) < (3, 10):
        raise RuntimeError("The system requires python version 3.10+")


def is_prod() -> bool:
    """检测当前是否为生产环境。

    优先读取 ``PASSPORT_ENV`` 环境变量，其次读取 ``FLASK_ENV``。

    :returns: 生产环境返回 True，开发环境返回 False
    """
    fe = getenv("FLASK_ENV")
    pe = getenv(f"{ENV_PREFIX}_ENV")
    prd = ("prod", "production")
    return (fe in prd) or (pe in prd)


def now() -> int:
    """获取当前 Unix 时间戳（10 位，秒级）。

    :returns: 当前时间戳（整数）
    """
    return int(time())


def timestamp_after_timestamp(
    timestamp: Optional[int] = None,
    seconds: int = 0,
    minutes: int = 0,
    hours: int = 0,
    days: int = 0,
) -> int:
    """给定时间戳（10 位），计算偏移后的时间戳（本地时区）。

    :param timestamp: 基准时间戳，默认为当前时间
    :param seconds: 偏移秒数
    :param minutes: 偏移分钟数
    :param hours: 偏移小时数
    :param days: 偏移天数
    :returns: 偏移后的 10 位 Unix 时间戳
    """
    timestamp = now() if timestamp is None else timestamp
    d1 = datetime.fromtimestamp(timestamp)
    d2 = d1 + timedelta(
        seconds=int(seconds),
        minutes=int(minutes),
        hours=int(hours),
        days=int(days),
    )
    return int(mktime(d2.timetuple()))


def check_uid_rule(uid: str) -> bool:
    """检查 uid 是否符合规范（长度为 22 的字符串）。

    :param uid: 待检查的用户唯一标识符
    :returns: 符合规则返回 True，否则返回 False
    """
    return len(uid) == 22 if isinstance(uid, str) else False


def auto_create_data_dir():
    """自动创建应用数据目录（APP_DIR/data），如果不存在则创建。"""
    if not exists(join(APP_DIR, "data")):
        makedirs(join(APP_DIR, "data"), exist_ok=True)
