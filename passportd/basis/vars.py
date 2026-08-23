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

from os.path import realpath, dirname
from typing import Dict, Union, Literal, TypedDict, List

try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired

# 定义类型区域
#: 配置项类型
LOG_LEVEL_TYPE = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
COMMON_VALUE_TYPE = Union[str, int, bool, None]
COMMON_DICT_TYPE = Dict[str, COMMON_VALUE_TYPE]


#: API Response Type
class ApiRespType(TypedDict):
    success: bool
    message: str
    data: NotRequired[Union[COMMON_DICT_TYPE, List[COMMON_DICT_TYPE], str]]


#: User Information Type
class UserInfoType(TypedDict):
    nickname: str
    bio: str
    gender: int
    avatar: str
    location: str
    role: str


#: OAuth User Information Type
class OAuthUserInfoType(TypedDict):
    account: str  # OAuth account identifier, e.g., "gitee:1234567"
    tpid: str  # Third-party ID, e.g., "1234567"
    name: str
    email: str
    gender: int
    picture: str
    location: str


# 定义公共变量区域
#: 进程名称
PROC_NAME: str = "passportd"
#: 程序目录
APP_DIR: str = dirname(dirname(realpath(__file__)))
#: Flask 读取环境变量前缀
ENV_PREFIX: str = "PASSPORT"
#: Flask from_envvar 读取环境变量名称
ENV_NAME: str = f"{ENV_PREFIX}_CONFIG"


# 定义应用变量区域
#: jwt编码解码
JWT_ALG: str = "HS256"
JWT_ISS: str = "SaintIC"
JWT_AUD: str = "Passport"
JWE_HEADER = {"alg": "RSA-OAEP", "enc": "A256GCM"}

#: OIDC
OIDC_EXP: int = 3600
OIDC_CODE_EXP: int = 300
OIDC_SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS: List[str] = [
    "client_secret_post",
    "client_secret_basic",
]
OIDC_SUPPORTED_SCOPES: List[str] = ["openid", "profile", "email", "role"]
OIDC_RSA_KEY_SIZE: int = 4096

#: 用户登录状态索引字段
USR_STATE_KEY: str = "sid"
#: 用户名修改间隔：3 个月（按 90 天计，秒）
USERNAME_CHANGE_INTERVAL: int = 90 * 24 * 3600
#: 用户背景图 Redis 缓存兜底时长（秒，默认 7 天）。修改背景图时主动刷新缓存为新值，
#: 正常情况下 TTL 不会触发，仅为异常兜底
USER_BG_CACHE_TTL: int = 604800
#: Apple Sign in with Apple client_secret 有效期（秒）。Apple 不使用固定 secret，
#: 要求调用方用 Team ID + Key ID + 私钥签发 JWT 作为 client_secret，有效期最长 180 天，
#: 程序每次换 token 时动态生成
APPLE_CLIENT_SECRET_TTL: int = 180 * 24 * 3600
#: Telegram 登录回执 auth_date 新鲜度窗口（秒），默认 86400（24h），防重放
TELEGRAM_AUTH_TTL: int = 86400
#: Telegram Bot 信息（getMe 结果）Redis 缓存时长（秒）。Bot Token 变更前 username 基本不变，
#: 缓存可避免每次打开登录页都请求 Telegram API
TELEGRAM_BOT_INFO_TTL: int = 3600

#: WebAuthn Passkey
#: Challenge 缓存有效期（秒）
PASSKEY_CHALLENGE_TTL: int = 300
#: Relying Party 名称，展示给用户的应用名称
PASSKEY_RP_NAME: str = PROC_NAME

#: Geetest Bypass URL
GEETEST_BYPASS_URL: str = "http://bypass.geetest.com/v1/bypass_status.php"
GEETEST_BYPASS_REDIS_KEY: str = f"{PROC_NAME}:bypass:status"
#: Bypass 状态检测分布式锁（gunicorn 多进程下仅一个实例执行检测）
GEETEST_BYPASS_LOCK_KEY: str = f"{PROC_NAME}:bypass:lock"
#: Bypass 状态检测间隔（秒）
GEETEST_BYPASS_INTERVAL: int = 100
#: Bypass 锁有效期（秒），需大于检测间隔，持锁进程崩溃后锁自动释放
GEETEST_BYPASS_LOCK_TTL: int = 200
