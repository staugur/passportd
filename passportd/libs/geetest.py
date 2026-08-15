# -*- coding: utf-8 -*-
"""GeeTest 行为验证（第三代）服务端官方封装 GeeTeam/gt3-server-python-flask-bypass"""

import hashlib
import hmac
import json
import os
import random
import threading
import time

import requests

from ..basis.conf import config
from ..basis.vars import (
    GEETEST_BYPASS_INTERVAL,
    GEETEST_BYPASS_LOCK_KEY,
    GEETEST_BYPASS_LOCK_TTL,
    GEETEST_BYPASS_REDIS_KEY,
    GEETEST_BYPASS_URL,
    PROC_NAME,
)
from ..utils.common import logger, rdb
from ..version import __version__


def geetest_enabled() -> bool:
    """是否启用 GeeTest 行为验证（验证 ID 与私钥均已配置）。

    :returns: 已启用返回 True
    """
    captcha_id = (config.get("GEETEST_CAPTCHA_ID") or "").strip()
    captcha_key = (config.get("GEETEST_CAPTCHA_KEY") or "").strip()
    return bool(captcha_id and captcha_key)


# sdk lib包的返回结果信息。
class GeetestLibResult:

    def __init__(self):
        self.status = 0  # 成功失败的标识码，1表示成功，0表示失败
        self.data = ""  # 返回数据，json格式
        self.msg = ""  # 备注信息，如异常信息等

    def set_all(self, status, data, msg):
        self.status = status
        self.data = data
        self.msg = msg

    def __str__(self):
        return "GeetestLibResult{{status={0}, data={1}, msg={2}}}".format(
            self.status, self.data, self.msg
        )


# sdk lib包，核心逻辑。
class GeetestLib:
    API_URL = "http://api.geetest.com"
    REGISTER_URL = "/register.php"
    VALIDATE_URL = "/validate.php"
    JSON_FORMAT = "1"
    NEW_CAPTCHA = True
    HTTP_TIMEOUT_DEFAULT = 5  # 单位：秒
    VERSION = f"{PROC_NAME}:{__version__}"
    GEETEST_CHALLENGE = "geetest_challenge"  # 极验二次验证表单传参字段 chllenge
    GEETEST_VALIDATE = "geetest_validate"  # 极验二次验证表单传参字段 validate
    GEETEST_SECCODE = "geetest_seccode"  # 极验二次验证表单传参字段 seccode

    def __init__(self, geetest_id, geetest_key):
        self.geetest_id = geetest_id
        self.geetest_key = geetest_key
        self.libResult = GeetestLibResult()

    # 验证初始化
    def register(self, digestmod, param_dict):
        logger.debug("register(): 开始验证初始化, digestmod={0}.".format(digestmod))
        origin_challenge = self.request_register(param_dict)
        self.build_register_result(origin_challenge, digestmod)
        logger.debug(
            "register(): 验证初始化, lib包返回信息={0}.".format(self.libResult)
        )
        return self.libResult

    def request_register(self, param_dict):
        param_dict.update(
            {
                "gt": self.geetest_id,
                "sdk": self.VERSION,
                "json_format": self.JSON_FORMAT,
            }
        )
        register_url = self.API_URL + self.REGISTER_URL
        logger.debug(
            "requestRegister(): 验证初始化, 向极验发送请求, url={0}, params={1}.".format(
                register_url, param_dict
            )
        )
        try:
            res = requests.get(
                register_url, params=param_dict, timeout=self.HTTP_TIMEOUT_DEFAULT
            )
            res_body = res.text if res.status_code == requests.codes.ok else ""
            logger.debug(
                "requestRegister(): 验证初始化, 与极验网络交互正常, 返回码={0}, 返回body={1}.".format(
                    res.status_code, res_body
                )
            )
            res_dict = json.loads(res_body)
            origin_challenge = res_dict["challenge"]
        except Exception as e:
            logger.debug(
                "requestRegister(): 验证初始化, 请求异常，后续流程走宕机模式, "
                + repr(e)
            )
            origin_challenge = ""
        return origin_challenge

    def local_init(self):
        self.build_register_result("", "")
        logger.debug(
            "local_init(): bypass当前状态为fail，后续流程将进入宕机模式, "
            + self.libResult.data
        )
        return self.libResult

    # 构建验证初始化返回数据
    def build_register_result(self, origin_challenge, digestmod):
        # origin_challenge为空或者值为0代表失败
        if not origin_challenge or origin_challenge == "0":
            # 本地随机生成32位字符串
            challenge = "".join(
                random.sample("abcdefghijklmnopqrstuvwxyz0123456789", 32)
            )
            data = json.dumps(
                {
                    "success": 0,
                    "gt": self.geetest_id,
                    "challenge": challenge,
                    "new_captcha": self.NEW_CAPTCHA,
                }
            )
            self.libResult.set_all(0, data, "bypass当前状态为fail，后续流程走宕机模式")
        else:
            if digestmod == "md5":
                challenge = self.md5_encode(origin_challenge + self.geetest_key)
            elif digestmod == "sha256":
                challenge = self.sha256_endode(origin_challenge + self.geetest_key)
            elif digestmod == "hmac-sha256":
                challenge = self.hmac_sha256_endode(origin_challenge, self.geetest_key)
            else:
                challenge = self.md5_encode(origin_challenge + self.geetest_key)
            data = json.dumps(
                {
                    "success": 1,
                    "gt": self.geetest_id,
                    "challenge": challenge,
                    "new_captcha": self.NEW_CAPTCHA,
                }
            )
            self.libResult.set_all(1, data, "")

    # 正常流程下（即验证初始化成功），二次验证
    def successValidate(self, challenge, validate, seccode, param_dict={}):
        logger.debug(
            "successValidate(): 开始二次验证 正常模式, challenge={0}, validate={1}, seccode={2}.".format(
                challenge, validate, seccode
            )
        )
        if not self.check_param(challenge, validate, seccode):
            self.libResult.set_all(
                0, "", "正常模式，本地校验，参数challenge、validate、seccode不可为空"
            )
        else:
            response_seccode = self.requestValidate(
                challenge, validate, seccode, param_dict
            )
            if not response_seccode:
                self.libResult.set_all(0, "", "请求极验validate接口失败")
            elif response_seccode == "false":
                self.libResult.set_all(0, "", "极验二次验证不通过")
            else:
                self.libResult.set_all(1, "", "")
        logger.debug(
            "successValidate(): 二次验证 正常模式, lib包返回信息={0}.".format(
                self.libResult
            )
        )
        return self.libResult

    # 异常流程下（即验证初始化失败，宕机模式），二次验证
    # 注意：由于是宕机模式，初衷是保证验证业务不会中断正常业务，所以此处只作简单的参数校验，可自行设计逻辑。
    def failValidate(self, challenge, validate, seccode):
        logger.debug(
            "failValidate(): 开始二次验证 宕机模式, challenge={0}, validate={1}, seccode={2}.".format(
                challenge, validate, seccode
            )
        )
        if not self.check_param(challenge, validate, seccode):
            self.libResult.set_all(
                0, "", "宕机模式，本地校验，参数challenge、validate、seccode不可为空."
            )
        else:
            self.libResult.set_all(1, "", "")
        logger.debug(
            "failValidate(): 二次验证 宕机模式, lib包返回信息={0}.".format(
                self.libResult
            )
        )
        return self.libResult

    # 向极验发送二次验证的请求，POST方式
    def requestValidate(self, challenge, validate, seccode, param_dict):
        param_dict.update(
            {
                "seccode": seccode,
                "json_format": self.JSON_FORMAT,
                "challenge": challenge,
                "sdk": self.VERSION,
                "captchaid": self.geetest_id,
            }
        )
        validate_url = self.API_URL + self.VALIDATE_URL
        logger.debug(
            "requestValidate(): 二次验证 正常模式, 向极验发送请求, url={0}, params={1}.".format(
                validate_url, param_dict
            )
        )
        try:
            res = requests.post(
                validate_url, data=param_dict, timeout=self.HTTP_TIMEOUT_DEFAULT
            )
            res_body = res.text if res.status_code == requests.codes.ok else ""
            logger.debug(
                "requestValidate(): 二次验证 正常模式, 与极验网络交互正常, 返回码={0}, 返回body={1}.".format(
                    res.status_code, res_body
                )
            )
            res_dict = json.loads(res_body)
            seccode = res_dict["seccode"]
        except Exception as e:
            logger.debug("requestValidate(): 二次验证 正常模式, 请求异常, " + repr(e))
            seccode = ""
        return seccode

    # 校验二次验证的三个参数，校验通过返回true，校验失败返回false
    def check_param(self, challenge, validate, seccode):
        return not (
            challenge is None
            or challenge.isspace()
            or validate is None
            or validate.isspace()
            or seccode is None
            or seccode.isspace()
        )

    def md5_encode(self, value):
        md5 = hashlib.md5()
        md5.update(value.encode("utf-8"))
        return md5.hexdigest()

    def sha256_endode(self, value):
        sha256 = hashlib.sha256()
        sha256.update(value.encode("utf-8"))
        return sha256.hexdigest()

    def hmac_sha256_endode(self, value, key):
        return hmac.new(
            key.encode("utf-8"), value.encode("utf-8"), digestmod=hashlib.sha256
        ).hexdigest()


def _fetch_bypass_status() -> None:
    """请求极验 bypass 接口并将状态写入 Redis，单次检测。

    :returns: 写入 Redis 的 bypass 状态（success/fail）
    :rtype: str
    """
    response = ""
    params = {"gt": config.get("GEETEST_CAPTCHA_ID")}
    try:
        response = requests.get(url=GEETEST_BYPASS_URL, params=params)
    except Exception as e:
        logger.error("geetest bypass request error: %s", e)
    if response and response.status_code == 200:
        bypass_status_str = response.content.decode("utf-8")
        bypass_status = json.loads(bypass_status_str).get("status")
    else:
        bypass_status = "fail"
    rdb.set(GEETEST_BYPASS_REDIS_KEY, bypass_status)
    logger.debug("bypass 状态已获取并存入 redis，当前状态为-%s", bypass_status)
    return bypass_status


# 发送bypass请求，获取bypass状态并进行缓存（守护线程常驻运行）
def check_bypass_status() -> None:
    """循环检测极验 bypass 状态并写入 Redis，供守护线程调用。

    gunicorn 多 worker 都会执行 create_app 并各自启动该循环，
    通过 Redis 分布式锁保证同时仅有一个实例实际请求极验，其余
    实例等待锁释放后接管，避免多进程重复检测。

    :returns: None
    """
    token = "{0}-{1}".format(os.getpid(), threading.get_ident())
    while True:
        try:
            if rdb.get(GEETEST_BYPASS_LOCK_KEY) == token:
                # 锁仍归本线程持有，续期并执行检测
                rdb.expire(GEETEST_BYPASS_LOCK_KEY, GEETEST_BYPASS_LOCK_TTL)
                _fetch_bypass_status()
            else:
                # 尝试抢占分布式锁，成功则执行检测
                acquired = rdb.set(
                    GEETEST_BYPASS_LOCK_KEY,
                    token,
                    nx=True,
                    ex=GEETEST_BYPASS_LOCK_TTL,
                )
                if acquired:
                    _fetch_bypass_status()
        except Exception as e:
            logger.error("geetest bypass check loop error: %s", e)
        time.sleep(GEETEST_BYPASS_INTERVAL)


def start_bypass_checker() -> None:
    """以守护线程方式启动 bypass 状态检测任务。

    供 Flask 应用启动（create_app）时调用；未启用 GeeTest 时不启动。

    :returns: None
    """
    if not geetest_enabled():
        return
    thread = threading.Thread(target=check_bypass_status, daemon=True)
    thread.start()


# 从缓存中取出当前缓存的bypass状态(success/fail)
def get_bypass_cache() -> str:
    bypass_status_cache = rdb.get(GEETEST_BYPASS_REDIS_KEY)
    return bypass_status_cache or "fail"  # type: ignore
