# -*- coding: utf-8 -*-
"""GeeTest 行为验证（第三代）服务端封装。

通过极验官方接口 register.php / validate.php 完成验证初始化与二次校验，
仅依赖 requests 与标准库，无需额外安装极验 SDK。
"""

import hashlib
import random
import string

import requests

from ..basis.conf import config

#: 极验接口基础地址
_GEETEST_API_URL = "https://api.geetest.com"
#: 验证初始化接口
_REGISTER_URL = f"{_GEETEST_API_URL}/register.php"
#: 二次校验接口
_VALIDATE_URL = f"{_GEETEST_API_URL}/validate.php"
#: 极验接口请求超时（秒）
_GEETEST_TIMEOUT = 3


def geetest_enabled() -> bool:
    """是否启用 GeeTest 行为验证（验证 ID 与私钥均已配置）。

    :returns: 已启用返回 True
    """
    captcha_id = (config.get("GEETEST_CAPTCHA_ID") or "").strip()
    private_key = (config.get("GEETEST_PRIVATE_KEY") or "").strip()
    return bool(captcha_id and private_key)


def geetest_prepare() -> dict:
    """调用极验初始化接口，生成前端所需的验证参数。

    :returns: 含 ``success`` / ``gt`` / ``challenge`` 字段的字典；
        极验服务不可用时 ``success=0``（降级模式，前端走离线验证）
    """
    captcha_id = (config.get("GEETEST_CAPTCHA_ID") or "").strip()
    private_key = (config.get("GEETEST_PRIVATE_KEY") or "").strip()
    challenge = _random_challenge()
    success = 0
    try:
        resp = requests.get(
            _REGISTER_URL,
            params={"gt": captcha_id, "json": 1},
            timeout=_GEETEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        data = {}
    if data.get("success") == 1 and data.get("challenge"):
        # 官方约定：将原始 challenge 与私钥拼接后 MD5，再返回前端
        challenge = _md5(data["challenge"] + private_key)
        success = 1
    return {"success": success, "gt": captcha_id, "challenge": challenge}


def verify_geetest_form(form: dict) -> bool:
    """校验表单提交的 GeeTest 验证结果，未启用时直接通过。

    :param form: 请求表单（request.form 或类似字典），需包含
        geetest_challenge / geetest_validate / geetest_seccode 字段
    :type form: dict
    :returns: 验证通过返回 True
    """
    if not geetest_enabled():
        return True
    return verify_geetest(
        form.get("geetest_challenge", ""),
        form.get("geetest_validate", ""),
        form.get("geetest_seccode", ""),
    )


def verify_geetest(challenge: str, validate: str, seccode: str) -> bool:
    """二次校验前端提交的行为验证结果。

    :param challenge: 前端提交的 geetest_challenge
    :param validate: 前端提交的 geetest_validate
    :param seccode: 前端提交的 geetest_seccode
    :returns: 验证通过返回 True
    """
    if not (challenge and validate and seccode):
        return False
    # 降级模式（offline）：前端生成的 validate 为 challenge 的 MD5
    if _md5(challenge) == validate:
        return True
    # 正常模式：本地签名校验
    private_key = (config.get("GEETEST_PRIVATE_KEY") or "").strip()
    if _md5(private_key + "geetest" + validate) != seccode:
        return False
    # 正常模式：请求极验服务器二次校验
    try:
        resp = requests.get(
            _VALIDATE_URL,
            params={
                "seccode": seccode,
                "challenge": challenge,
                "captchaid": (config.get("GEETEST_CAPTCHA_ID") or "").strip(),
                "json": 1,
            },
            timeout=_GEETEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return False
    return data.get("seccode") == _md5(seccode)


def _md5(value: str) -> str:
    """计算字符串的 MD5 十六进制摘要。"""
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _random_challenge() -> str:
    """生成降级模式使用的随机挑战码。"""
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=32)
    )
