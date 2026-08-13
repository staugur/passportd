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

import sys
import logging
from logging.handlers import TimedRotatingFileHandler
from base64 import urlsafe_b64decode, urlsafe_b64encode
from json import loads as json_loads, dumps as json_dumps
from re import compile, IGNORECASE, fullmatch, search as re_search
from uuid import uuid4
from hashlib import sha256
from typing import Dict, Any, Union, Optional, List, Tuple
from urllib.parse import urlparse
from random import sample
from os import makedirs
from os.path import dirname, join, isfile

from shortuuid import uuid as shortuuid
from joserfc import jwt, jwe
from joserfc.jwk import OctKey, RSAKey
from joserfc.errors import JoseError
from redis import from_url, Redis

from ..basis.vars import (
    JWT_ALG,
    JWT_ISS,
    JWT_AUD,
    PROC_NAME,
    JWE_HEADER,
    COMMON_DICT_TYPE,
)
from ..basis.common import now, timestamp_after_timestamp
from ..basis.conf import config
from ..basis.errors import JWTError, ParamError

mail_pat = compile(r"([0-9a-zA-Z\_*\.*\-*\+]+)@([a-zA-Z0-9\-*\_*\.*]+)\.([a-zA-Z]+$)")
mobile_pat = compile(r"^1[3-9]\d{9}$")
username_pat = compile(r"^[a-z][0-9a-z\_]{3,31}$")
thirdaccount_pat = compile(r"^([a-zA-Z][a-zA-Z0-9_]+)\.([a-zA-Z0-9_\-]{3,32})$")
appname_pat = compile(r"^[a-z][0-9a-z\_\-]{3,32}$")


def email_check(email: str) -> bool:
    """校验邮箱格式是否合法。

    :param email: 邮箱地址字符串
    :returns: 合法返回 True，否则 False
    """
    if email and isinstance(email, str):
        return True if mail_pat.match(email) else False
    return False


def phone_check(phone: str) -> bool:
    """校验手机号格式是否合法（中国大陆 1[3-9] 开头 11 位）。

    :param phone: 手机号字符串
    :returns: 合法返回 True，否则 False
    """
    if phone and isinstance(phone, str):
        return True if mobile_pat.match(phone) else False
    return False


def username_check(user: str) -> bool:
    """校验用户名格式是否合法（小写字母开头，3-32 位小写字母/数字/下划线）。

    :param user: 用户名字符串
    :returns: 合法返回 True，否则 False
    """
    if user and isinstance(user, str):
        return True if username_pat.match(user) else False
    return False


def multi_phone_check(phone: str) -> bool:
    """验证支持多个手机号，分隔符为英文逗号"""
    if phone and isinstance(phone, str):
        for p in phone.split(","):
            if not phone_check(p):
                return False
        return True
    return False


def is_local_account(account: str) -> bool:
    """是否为本地化账号，只要符合username、email、phone任意格式即可"""
    if not account or not isinstance(account, str):
        return False
    return username_check(account) or email_check(account) or phone_check(account)


def is_third_account(account: str) -> bool:
    """检查是否为第三方（OAuth）账号，格式是 oauth_name.username。"""
    if not account or not isinstance(account, str):
        return False
    return True if thirdaccount_pat.match(account) else False


def appname_check(name: str) -> bool:
    """检查 OAuth Client 应用名称是否符合规范"""
    if name and isinstance(name, str):
        return True if appname_pat.match(name) else False
    return False


def parse_account_classify(name: str) -> Optional[str]:
    """从账号中解析出账号类型，本地账号类型直接显示，如username，三方账号返回3rd"""
    if is_local_account(name):
        if username_check(name):
            return "username"
        elif email_check(name):
            return "email"
        elif phone_check(name):
            return "mobile"
    elif is_third_account(name):
        return "3rd"


def parse_db_uri(uri: str) -> COMMON_DICT_TYPE:
    """解析数据库连接 URI，提取各组成部分。

    :param uri: 数据库连接 URI 字符串
    :returns: 包含 provider、host、database 等字段的字典
    """
    if not uri:
        return {}
    p = urlparse(uri)
    opt = dict(provider=p.scheme)
    if p.scheme in ("sqlite", "file"):
        opt.update(filename=p.path, create_db=True)
        return opt
    if "@" in p.netloc:
        auth, host = p.netloc.split("@")
        if ":" in auth:
            user, pwd = auth.split(":")
        else:
            user = auth
            pwd = None
        opt.update(user=user, password=pwd)
    else:
        host = p.netloc
    opt.update(host=host, database=p.path.lstrip("/"))
    return opt


def is_valid_http_url(url: str) -> bool:
    """校验字符串是否为合法的 HTTP/HTTPS URL。

    支持域名、localhost、IPv4 地址，可选端口号和路径。

    :param url: 待校验 URL 字符串
    :returns: 合法返回 True，否则 False
    """
    if not url:
        return False
    pattern = compile(
        r"^https?://"  # 协议部分
        r"(?:"  # 域名或IP部分
        r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}"  # 标准域名
        r"|localhost"  # localhost
        r"|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # IPv4地址
        r"(?::\d+)?"  # 端口号（可选）
        r"(?:/[\w\-\.~%!$&\'()*+,;=:@]*)*"  # 路径（可选）
        r"(?:\?[^\s#]*)?"  # 查询参数（可选）
        r"(?:#\S*)?$",  # 锚点（可选）
        IGNORECASE,
    )
    return pattern.match(url) is not None


def is_valid_ipv4(ip):
    """校验字符串是否为合法的 IPv4 地址。

    :param ip: 待校验 IP 地址字符串
    :returns: 合法返回 True，否则 False
    """
    pattern = r"^((25[0-5]|2[0-4]\d|1\d{2}|0\d{1,2}|[1-9]?\d)\.){3}(25[0-5]|2[0-4]\d|1\d{2}|0\d{1,2}|[1-9]?\d)$"
    return fullmatch(pattern, ip) is not None


def is_valid_user_role(role: str) -> bool:
    """校验用户角色格式是否合法。

    支持两种格式：
    - 内置角色（小写）：``superadmin``、``admin``、``user``
    - 客户端角色：``client_name:Role`` 格式，其中 ``client_name`` 需通过
      ``appname_check`` 校验（如 ``myapp:Admin``）

    :param role: 角色字符串
    :returns: 合法返回 True，否则 False
    """
    if role in ("superadmin", "admin", "user"):
        return True
    if isinstance(role, str):
        parts = role.split(":")
        if len(parts) == 2 and appname_check(parts[0]) and parts[1]:
            return True
    return False


def create_log() -> logging.Logger:
    """创建并配置应用日志实例。

    根据 ``LOG_LEVEL``、``LOG_FILE`` 配置项创建：

    - 有 LOG_FILE 时使用 TimedRotatingFileHandler（按日期轮转），
      日志文件写入 ``BASE_DIR/logs/`` 目录
    - 无 LOG_FILE 时输出到 stdout

    :returns: 配置好的 Logger 实例
    """
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    logfmt = "[ %(levelname)s ] %(asctime)s %(filename)s:%(lineno)d %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(logfmt, datefmt=datefmt)
    logger = logging.getLogger(PROC_NAME)
    logger.setLevel(levels[config["LOG_LEVEL"]])
    if config.get("LOG_FILE"):
        log_dir = join(config["BASE_DIR"], "logs")
        makedirs(log_dir, exist_ok=True)
        log_file = join(log_dir, config["LOG_FILE"])
        # 创建文件处理器（按时间分隔），写入日志文件
        handler = TimedRotatingFileHandler(
            filename=log_file,
            backupCount=10,
            when="midnight",
            encoding="utf-8",
        )
        handler.suffix = "%Y%m%d"
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        # 创建流处理器，输出到 stdout
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def create_redis_engine(redis_url: str) -> Redis:
    """创建 Redis 连接池实例。

    :param redis_url: Redis 连接 URL（``redis://[:password]@host[:port/db]``）
    :returns: Redis 客户端实例
    :raises ParamError: redis_url 无效时抛出
    """
    if not redis_url:
        raise ParamError("invalid redis url")
    return from_url(redis_url, decode_responses=True)


def gen_uid() -> str:
    """生成唯一用户标识符（基于 shortuuid，22 位小写字符串）。

    :returns: 生成的 uid 字符串
    """
    return shortuuid().lower()


def jwt_encode(
    secret_key: str, payload: Optional[Dict[str, Any]] = None, expire: int = 3600
) -> str:
    """使用 HS256 算法编码 JWT。

    :param secret_key: 用于签名的密钥
    :param payload: 自定义 claims 字典，会自动补充 ``iss``、``iat``、``exp``、``aud``、``jti``
    :param expire: 过期时间（秒），最小 300
    :returns: JWT 字符串
    :raises ParamError: expire < 300 时抛出
    """
    if expire < 300:
        raise ParamError("JWT expire time must be at least 5 minutes")
    h = {"alg": JWT_ALG}
    n = now()
    d = dict(
        iss=JWT_ISS,
        iat=n,
        exp=timestamp_after_timestamp(n, seconds=expire),
        aud=JWT_AUD,
        jti=str(uuid4()),
    )
    if isinstance(payload, dict):
        payload.update(d)
    else:
        payload = d
    key = OctKey.import_key(secret_key)
    return jwt.encode(h, payload, key)


def jwt_decode(
    encrypted_text: Union[str, bytes],
    secret_key: str,
    sub: Optional[str] = None,
) -> Dict[str, Union[str, int]]:
    """验证并解码 JWT。

    会校验 ``iss``、``aud``、``jti``、``exp`` 以及可选的 ``sub`` 声明。

    :param encrypted_text: JWT 字符串或字节
    :param secret_key: 用于验证签名的密钥
    :param sub: 可选的 subject 声明，提供则严格校验
    :returns: 解码后的 claims 字典
    :raises JWTError: 解码或校验失败时抛出
    """
    if not encrypted_text or not secret_key:
        raise JWTError("Invalid params")
    try:
        key = OctKey.import_key(secret_key)
        token = jwt.decode(
            encrypted_text,
            key,
            algorithms=[JWT_ALG],
        )
        options = dict(
            exp={"essential": True},
            iss={"essential": True, "value": JWT_ISS},
            aud={"essential": True, "value": JWT_AUD},
            jti={"essential": True},
        )
        if sub:
            options["sub"] = {"essential": True, "value": sub}
        claims_requests = jwt.JWTClaimsRegistry(**options)
        claims_requests.validate(token.claims)
    except JoseError as e:
        raise JWTError(e)
    else:
        return dict(token.claims)  # type: ignore


def jwt_decode_payload_without_verify(token: str) -> Dict[str, Union[str, int]]:
    """解析 JWT 的 payload 部分（不验证签名）。

    仅解码 payload，不校验签名或过期时间。适用于调试或日志记录等需要
    快速提取 claims 但无需可信验证的场景。

    :param token: 待解析的 JWT 令牌字符串，不能为空
    :returns: 解析后的 payload 字典，通常包含声明（claims）信息
    :raises ValueError: token 为空或格式无效（不是标准的三段式 JWT）时抛出
    """
    if not token:
        raise ValueError("Invalid JWT token")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT token")

    payload_encoded = parts[1]
    payload_encoded += "=" * (4 - (len(payload_encoded) % 4))
    payload_decoded = urlsafe_b64decode(payload_encoded)
    return json_loads(payload_decoded)


def generate_verification_code(length: int = 6) -> str:
    """生成随机字母数字验证码。

    从 0-9 数字、A-Z 大写字母、a-z 小写字母的字符池中随机采样指定长度。

    :param length: 验证码长度，默认 6
    :returns: 随机生成的验证码字符串
    """
    code_list = []
    for i in range(10):  # 0-9数字
        code_list.append(str(i))
    for i in range(65, 91):  # A-Z
        code_list.append(chr(i))
    for i in range(97, 123):  # a-z
        code_list.append(chr(i))

    myslice = sample(code_list, length)  # 从list中随机获取6个元素，作为一个片断返回
    verification_code = "".join(myslice)  # list to string
    return verification_code


def generate_digital_verification_code(length: int = 6) -> str:
    """生成纯数字验证码。

    从 0-9 数字中随机采样指定长度的数字验证码。

    :param length: 验证码长度，默认 6
    :returns: 随机生成的纯数字验证码字符串
    """
    code = []
    code = "".join(str(i) for i in sample(range(0, 10), length))
    return code


def auto_init_rsa_key():
    """Automatically generate an RSA key if it does not exist."""
    pubkey = config["OIDC_RSA_PUBLIC_KEY"]
    prikey = config["OIDC_RSA_PRIVATE_KEY"]
    from ..basis.vars import OIDC_RSA_KEY_SIZE as _rsa_keysize

    keysize = _rsa_keysize
    if not isinstance(keysize, int) or keysize < 1024:
        raise ParamError("Invalid RSA key size: {}".format(keysize))
    if not isfile(pubkey) or not isfile(prikey):
        rsa = RSAKey.generate_key(keysize)
        with open(prikey, "w") as fp:
            fp.write(rsa.as_pem(private=True).decode("utf-8"))
        with open(pubkey, "w") as fp:
            fp.write(rsa.as_pem(private=False).decode("utf-8"))


def read_rsa_public_key() -> str:
    """Read the public key from the file."""
    pubkey = config["OIDC_RSA_PUBLIC_KEY"]
    if not isfile(pubkey):
        raise ParamError("Public key file does not exist.")
    with open(pubkey, "r") as fp:
        return fp.read()


def read_rsa_private_key() -> str:
    """Read the private key from the file."""
    prikey = config["OIDC_RSA_PRIVATE_KEY"]
    if not isfile(prikey):
        raise ParamError("Private key file does not exist.")
    with open(prikey, "r") as fp:
        return fp.read()


def rsa_encrypt(plaintext: str) -> str:
    """使用RSA公钥对明文进行JWE加密。

    依赖 ``read_rsa_public_key`` 读取RSA公钥，通过 ``joserfc.jwe`` 模块加密，
    返回符合 JWE (JSON Web Encryption) 标准的紧凑序列化字符串。

    :param plaintext: 需要加密的明文内容，不能为空字符串或 None
    :returns: JWE 紧凑序列化后的密文字符串
    :rtype: str
    :raises ParamError: plaintext 为空或 None 时抛出
    """
    if not plaintext:
        raise ParamError("Invalid plaintext")
    pub_key = RSAKey.import_key(read_rsa_public_key())
    return jwe.encrypt_compact(JWE_HEADER, plaintext, pub_key)


def rsa_decrypt(ciphertext: str) -> bytes:
    """使用RSA私钥解密JWE密文。

    依赖 ``joserfc.jwe`` 模块进行解密，私钥通过 ``read_rsa_private_key`` 读取。
    返回的 plaintext 是二进制数据，调用方需根据业务需求进一步处理。

    :param ciphertext: JWE 紧凑序列化格式的密文字符串，不能为空字符串或 None
    :returns: 解密后的原始明文数据
    :rtype: bytes
    :raises ParamError: ciphertext 为空或 None 时抛出
    """
    if not ciphertext:
        raise ParamError("Invalid ciphertext")
    pri_key = RSAKey.import_key(read_rsa_private_key())
    obj = jwe.decrypt_compact(ciphertext, pri_key)
    return obj.plaintext  # type: ignore


def parse_encrypted_password(encrypted_password: str) -> str:
    """尝试解密密码，解密失败时返回空字符串。

    :param encrypted_password: RSA 加密后的密码（JWE 格式）
    :returns: 解密后的明文密码，失败返回空字符串
    """
    if encrypted_password:
        try:
            password = rsa_decrypt(encrypted_password)
        except Exception as e:
            pass
        else:
            return password.decode("utf-8")
    return ""


def compute_kid(private_key_pem: str) -> str:
    """计算 JWK SHA-256 Thumbprint（RFC 7638），用作 Key ID。

    :param private_key_pem: RSA 私钥 PEM 字符串
    :returns: base64url 编码的 SHA-256 指纹（不含末尾 = 填充）
    """
    key = RSAKey.import_key(private_key_pem)
    pub_jwk = key.as_dict(private=False)
    thumbprint_input = json_dumps(
        {"e": pub_jwk["e"], "kty": pub_jwk["kty"], "n": pub_jwk["n"]},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = sha256(thumbprint_input).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


#: log instance
logger = create_log()


#: redis client connpoll
rdb: Redis = create_redis_engine(config["REDIS_URI"])


# ---------------------------------------------------------------------------
# User-Agent 解析 & 浏览器指纹
# ---------------------------------------------------------------------------

_UA_REGEX_MAP: Dict[str, List[Tuple[str, str]]] = {
    "browser": [
        (r"Edg(?:e|A|iOS)?/(\S+)", "Edge"),
        (r"CriOS/(\S+)", "Chrome"),
        (r"FxiOS/(\S+)", "Firefox"),
        (r"OPR/(\S+)", "Opera"),
        (r"OPiOS/(\S+)", "Opera"),
        (r"(?:Chrome|Chromium)/(\S+)", "Chrome"),
        (r"Firefox/(\S+)", "Firefox"),
        (r"Safari/(\S+)", "Safari"),
        (r"MSIE\s+(\S+)", "IE"),
        (r"Trident.*rv:(\S+)", "IE"),
    ],
    "os": [
        (r"Windows\s+NT\s+10", "Windows 10"),
        (r"Windows\s+NT\s+6\.3", "Windows 8.1"),
        (r"Windows\s+NT\s+6\.2", "Windows 8"),
        (r"Windows\s+NT\s+6\.1", "Windows 7"),
        (r"Windows\s+NT\s+\d+", "Windows"),
        (r"Mac\s+OS\s+X\s+10[._](\d+)", "macOS"),
        (r"iPhone.*OS\s+(\d+[._]\d+)", "iOS"),
        (r"iPad.*OS\s+(\d+[._]\d+)", "iPadOS"),
        (r"Android\s+(\d+[._]?\d*)", "Android"),
        (r"Linux", "Linux"),
        (r"CrOS\s+\S+", "ChromeOS"),
    ],
    "device": [
        (r"iPhone|iPod", "Mobile"),
        (r"iPad", "Tablet"),
        (r"Android.*(?:Mobile|mobi)", "Mobile"),
        (r"Android.*(?:Tablet|tab)", "Tablet"),
        (r"Android", "Mobile"),
        (r"Mobile", "Mobile"),
    ],
}


def parse_user_agent(ua: str) -> Tuple[str, str, str]:
    """从 User-Agent 字符串中提取浏览器、操作系统、设备类型。

    :returns: (browser, os, device) 三元组
    """
    browser = "Unknown"
    os_name = "Unknown"
    device = "Desktop"

    for pattern, name in _UA_REGEX_MAP["browser"]:
        if re_search(pattern, ua, IGNORECASE):
            browser = name
            break

    for pattern, name in _UA_REGEX_MAP["os"]:
        m = re_search(pattern, ua, IGNORECASE)
        if m:
            os_name = name
            if name in ("macOS",) and m.group(1):
                os_name = f"macOS {m.group(1).replace('_', '.')}"
            elif name == "iOS" and m.group(1):
                os_name = f"iOS {m.group(1).replace('_', '.')}"
            elif name == "Android" and m.group(1):
                os_name = f"Android {m.group(1).replace('_', '.')}"
            break

    for pattern, name in _UA_REGEX_MAP["device"]:
        if re_search(pattern, ua, IGNORECASE):
            device = name
            break

    return browser, os_name, device


def generate_fingerprint(ip: str, ua: str, accept_lang: str) -> str:
    """基于 IP + UA + Accept-Language 生成简易浏览器指纹。

    :returns: SHA256 十六进制字符串
    """
    raw = f"{ip}|{ua}|{accept_lang}"
    return sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# WebAuthn Passkey 工具函数
# ---------------------------------------------------------------------------


def base64url_encode(data: bytes) -> str:
    """将 bytes 编码为 base64url（不含末尾 = 填充）字符串。

    WebAuthn 协议全程使用 base64url，此函数封装了标准编码。
    """
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def base64url_decode(s: str) -> bytes:
    """将 base64url 字符串解码为原始 bytes，自动补齐末尾 = 填充。"""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return urlsafe_b64decode(s.encode("ascii"))


def generate_passkey_challenge() -> bytes:
    """生成 WebAuthn 随机 challenge（32 字节）。"""
    from os import urandom

    return urandom(32)


def save_passkey_challenge(key: str, challenge: bytes, ttl: int = 300) -> bool:
    """将 WebAuthn challenge 存入 Redis。

    :param key: 缓存键（如 uid 或 session_id）
    :param challenge: 原始 challenge bytes
    :param ttl: 过期时间，默认 300 秒
    :returns: 是否设置成功
    """
    redis_key = f"{PROC_NAME}:passkey:challenge:{key}"
    return bool(rdb.set(redis_key, base64url_encode(challenge), ex=ttl))


def get_passkey_challenge(key: str) -> Optional[bytes]:
    """从 Redis 读取 WebAuthn challenge 并删除（一次性使用）。

    :param key: 缓存键
    :returns: challenge bytes，不存在时返回 None
    """
    redis_key = f"{PROC_NAME}:passkey:challenge:{key}"
    encoded = rdb.get(redis_key)
    if encoded:
        rdb.delete(redis_key)
        return base64url_decode(
            encoded.decode("utf-8") if isinstance(encoded, bytes) else encoded
        )
    return None
