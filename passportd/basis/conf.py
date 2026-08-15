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

from os.path import join
from typing import Optional

from flask import Config as FlaskConfig

from .common import is_passkey_enabled, is_prod
from .vars import (
    APP_DIR,
    ENV_NAME,
    ENV_PREFIX,
    LOG_LEVEL_TYPE,
    PROC_NAME,
)

__all__ = ["config"]

_gen_data_path = lambda f: join(APP_DIR, "data", f)  # type: ignore


class BaseConfig:
    """应用全局基础配置。

    所有配置项均支持通过环境变量 ``PASSPORT_<KEY>`` 覆盖。
    """

    # 全局配置
    ENV = "production"
    DEBUG = False
    #: 签名、认证密钥，至少14位，建议32位以上。
    SECRET_KEY: str = "change-secret-at-least-32-bytes"
    #: 监听地址
    HOST: str = "0.0.0.0"
    #: 监听端口
    PORT: int = 10030
    #: 数据根目录，data/logs/uploads 均在此目录下创建子目录，容器环境可设为 /app
    BASE_DIR: str = APP_DIR
    #: 数据库连接配置，格式 scheme://user:password@host:port/dbname?option=value
    #: https://docs.peewee-orm.com/en/latest/peewee/db_tools.html
    #: SQLite 使用 sqlite:///path, 注意是三个斜杠，path如果是绝对路径则是四个斜杠。
    #: MySQL/MariaDB 使用 mysql+pool://, PostgreSQL 使用 psycopg3+pool://。
    DB_URI: str = "sqlite:///{}.db".format(_gen_data_path(PROC_NAME))
    #: Redis 缓存配置
    #: 格式为 redis://[:password]@host[:port/db]
    REDIS_URI = "redis://localhost:6379/0"
    #: 日志配置
    LOG_LEVEL: LOG_LEVEL_TYPE = "DEBUG"
    LOG_FILE: Optional[str] = None
    #: 全局URL前缀
    URI_PREFIX: str = "/"
    #: 公告通知配置。支持两种格式：
    #: 1. list: [{"content": "公告内容", "ctime": 时间戳, "etime": 0或时间戳, "closable": bool}]
    #:    ctime 创建时间，etime 过期时间（0=永不过期），closable 是否允许关闭（默认 true）
    #: 2. str: URL 地址，需返回 JSON: {success, data: [...]}
    NOTICE = []
    #: IP 地理位置查询接口
    IP_API_URL: str = "https://hub.saintic.com/openservice/ip/rest"

    # 站点配置
    #: ICP备案号
    SITE_ICP: str = ""
    #: 站点标题，用于浏览器标题、导航栏品牌、页脚版权等，为空回退 "Passport"
    SITE_TITLE: str = "Passport"
    #: 站点描述，用于 meta description（SEO）
    SITE_DESC: str = ""
    #: 站点关键词，英文逗号分隔，用于 meta keywords（SEO）
    SITE_KEYWORDS: str = ""
    #: 站点 favicon 地址（URL 或静态资源路径），为空使用默认静态图标
    SITE_FAVICON: str = ""
    #: 站点 logo 图片地址（URL），为空导航栏显示 SITE_TITLE 文字
    SITE_LOGO: str = ""
    #: 是否启用隐私政策页面（/privacy），true 时页脚显示「隐私政策」链接
    SITE_PRIVACY: bool = False

    # 上传
    #: 上传方式，支持 sapic、local，本地上传固定保存到 BASE_DIR/uploads
    UPLOAD_METHOD = "local"
    #: Sapic 上传接口和LinkToken，文档是 https://sapic.rtfd.vip
    SAPIC_APIURL = "https://sapicd.com"
    SAPIC_LINKTOKEN = ""

    # 邮件
    #: 邮件发送方式，支持 支持空字符串（不发送）、smtp、spug
    EMAIL_PROVIDER = ""
    #: SMTP邮箱服务器
    ## 发送邮件的邮箱地址
    SMTP_USER_MAIL: str = ""
    ## 邮箱用户的密码
    SMTP_USER_PASSWD: str = ""
    ## 发送邮件服务器地址
    SMTP_SERVER: str = ""
    ## 发送邮件服务器端口
    ## 由端口自动判断：465=SSL/TLS(SMTP_SSL), 其他=明文+STARTTLS, 25端口禁止使用
    ## 国内主流邮箱（QQ/163/阿里/腾讯企业邮）均使用 465 端口
    SMTP_PORT: int = 465
    #: SPUG推送助手邮件配置
    SPUG_MAIL_TEMPLATE_ID = ""

    # 短信
    #: 短信发送方式，支持空字符串（不发送）、spug
    SMS_PROVIDER = ""
    #: SPUG推送助手，短信模板ID
    SPUG_SMS_TEMPLATE_ID = ""

    # WebAuthn Passkey
    #: Relying Party ID，即当前服务的有效域名，如 example.com、passport.example.com。
    #: 开发环境可用 localhost；为空或无效值时 Passkey 功能不可用。
    PASSKEY_RP_ID: str = ""

    # OAuth2 配置
    #: GitHub OAuth2 配置
    GITHUB_CLIENT_ID = ""
    GITHUB_CLIENT_SECRET = ""
    GITHUB_CALLBACK_PROXY = None

    #: Gitee OAuth2 配置
    GITEE_CLIENT_ID = ""
    GITEE_CLIENT_SECRET = ""

    #: Weibo OAuth2 配置
    WEIBO_CLIENT_ID = ""
    WEIBO_CLIENT_SECRET = ""

    #: QQ OAuth2 配置
    QQ_CLIENT_ID = ""
    QQ_CLIENT_SECRET = ""

    #: Google OAuth2 配置
    GOOGLE_CLIENT_ID = ""
    GOOGLE_CLIENT_SECRET = ""
    GOOGLE_CALLBACK_PROXY = None

    # OIDC 内部客户端（自家应用）信任配置
    #: 自家应用 name 列表，英文逗号分隔（容忍逗号两侧空格）。仅列表内的
    #: 应用在申请 ``role`` scope 时可获得用户平台角色（admin / superadmin /
    #: user），第三方客户端一律不输出平台角色。环境变量示例
    #: ``PASSPORT_OIDC_INTERNAL_CLIENTS="my-app, your-app"``。
    OIDC_INTERNAL_CLIENTS: str = ""

    # Prometheus Metrics
    #: 是否启用 Prometheus 指标采集，关闭后 /metrics 返回 503
    METRICS_ENABLED: bool = True
    #: 指标端点路径（相对 URI_PREFIX）
    METRICS_PATH: str = "/metrics"
    #: 进程/业务/Redis 指标的缓存时间（秒），避免每次抓取都全量扫描
    METRICS_CACHE_TTL: int = 30
    #: 可选 Bearer Token 鉴权，为空则不鉴权；Prometheus 抓取时需携带
    #: Authorization: Bearer <token>
    METRICS_TOKEN: str = ""

    # 登录安全（暴力破解防护）
    #: 同一账号连续密码错误达到该次数后临时锁定
    LOGIN_FAIL_MAX: int = 5
    #: 账号临时锁定时间（秒），到期自动解锁
    LOGIN_LOCK_TIME: int = 900
    #: 同一 IP 在窗口时间内允许的最大登录/验证码请求次数
    LOGIN_IP_LIMIT: int = 20
    #: IP 限流统计窗口（秒）
    LOGIN_IP_WINDOW: int = 60


class DevConfig(BaseConfig):
    """默认开发环境配置。"""

    ENV = "development"
    DEBUG = True
    PASSKEY_RP_ID: str = "localhost"
    SITE_PRIVACY = True
    # Flask-PluginKit 配置
    PLUGINKIT_AUTH_METHOD = "FUNC"
    PLUGINKIT_AUTH_FUNC = lambda: True


class ProdConfig(BaseConfig):
    """默认生产环境配置。"""

    ENV = "production"
    DEBUG = False
    DB_URI = "psycopg3+pool://user:pwd@postgresql:5432/db?max_connections=20&stale_timeout=300"
    REDIS_URI = "redis://:pwd@localhost:6379/0"
    LOG_LEVEL = "INFO"
    LOG_FILE = "sys.log"
    #: 生产gunicorn运行配置
    NO_DAEMON: bool = False


class PinConfig:
    """固定配置类，不可被环境变量覆盖，在 from_prefixed_env 之后加载。

    以下值从 BASE_DIR 固定派生：
    - DATA_DIR: BASE_DIR/data
    - OIDC_RSA_PUBLIC_KEY / OIDC_RSA_PRIVATE_KEY: BASE_DIR/data/ 下的 RSA 密钥
    - LOCAL_UPLOAD_FOLDER: BASE_DIR/uploads
    """

    @classmethod
    def apply(cls, cfg):
        """从 BASE_DIR 派生固定路径并加载到 config。"""
        _base_dir = cfg.get("BASE_DIR", APP_DIR)
        cls.DATA_DIR = join(_base_dir, "data")
        cls.OIDC_RSA_PUBLIC_KEY = join(_base_dir, "data", "public.pem")
        cls.OIDC_RSA_PRIVATE_KEY = join(_base_dir, "data", "private.key")
        cls.LOCAL_UPLOAD_FOLDER = join(_base_dir, "uploads")
        cfg.from_object(cls)

        # DB_URI 中 APP_DIR 替换为 BASE_DIR
        if _base_dir != APP_DIR:
            db_uri = cfg.get("DB_URI", "")
            if isinstance(db_uri, str) and APP_DIR in db_uri:
                cfg["DB_URI"] = db_uri.replace(APP_DIR, _base_dir)


def _check_config_value(cfg):
    """对配置进行完整性校验，不满足条件则抛出 AssertionError。

    校验项包括：
    - PORT 为整数
    - DB_URI 格式校验（SQLite 使用 sqlite://，MySQL 使用 mysql+pool:// 连接池，PostgreSQL 使用 psycopg3+pool://）
    - REDIS_URI 以 ``redis://`` 开头
    - URI_PREFIX 以 ``/`` 开头
    - RSA 密钥大小为整数
    - 上传方式、邮件提供商和短信提供商的参数完整性
    - 登录安全配置（LOGIN_*）为正整数
    - LOG_LEVEL 为合法日志级别
    - METRICS_* 类型与取值（ENABLED 为布尔、PATH 以 / 开头、CACHE_TTL 为正整数）
    - NOTICE 为 list 或 URL 字符串
    - 站点等字符串配置为 str

    :param cfg: Flask Config 实例
    :type cfg: flask.Config
    :raises AssertionError: 配置不符合要求时抛出
    """
    assert isinstance(cfg, FlaskConfig), "Config must be an instance of flask.Config"
    assert isinstance(cfg["PORT"], int), "Port must be a integer"
    assert (
        len(cfg["SECRET_KEY"]) >= 14
    ), "SECRET_KEY must be at least 14 bytes (112 bits)"
    assert cfg["DB_URI"].split("://")[0] in [
        "sqlite",
        "mysql+pool",
        "psycopg3+pool",
    ], "DB_URI must start with sqlite, mysql+pool, or psycopg3+pool"
    assert cfg["REDIS_URI"].startswith("redis://"), "REDIS_URI must start with redis://"
    assert cfg["URI_PREFIX"].startswith("/"), "URI_PREFIX must start with /"
    assert cfg["LOG_LEVEL"] in [
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ], "LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL"

    assert cfg["UPLOAD_METHOD"] in [
        "sapic",
        "local",
    ], "UPLOAD_METHOD must be 'sapic' or 'local'"
    if cfg["UPLOAD_METHOD"] == "sapic":
        assert (
            cfg["SAPIC_APIURL"] != None
        ), "SAPIC_APIURL must be set when UPLOAD_METHOD is 'sapic'"

    assert cfg["EMAIL_PROVIDER"] in [
        "",
        "smtp",
        "spug",
    ], "EMAIL_PROVIDER must be empty or 'smtp' or 'spug'"
    if cfg["EMAIL_PROVIDER"] == "smtp":
        assert (
            cfg["SMTP_USER_MAIL"]
            and cfg["SMTP_USER_PASSWD"]
            and cfg["SMTP_SERVER"]
            and isinstance(cfg["SMTP_PORT"], int)
            and cfg["SMTP_PORT"] != 25
        ), "SMTP_USER_MAIL, SMTP_USER_PASSWD, SMTP_SERVER and SMTP_PORT must be set when EMAIL_PROVIDER is 'smtp', and SMTP_PORT must not be 25"
    elif cfg["EMAIL_PROVIDER"] == "spug":
        assert cfg[
            "SPUG_MAIL_TEMPLATE_ID"
        ], "SPUG_MAIL_TEMPLATE_ID must be set when EMAIL_PROVIDER is 'spug'"

    assert cfg["SMS_PROVIDER"] in [
        "",
        "spug",
    ], "SMS_PROVIDER must be empty or 'spug'"
    if cfg["SMS_PROVIDER"] == "spug":
        assert cfg[
            "SPUG_SMS_TEMPLATE_ID"
        ], "SPUG_SMS_TEMPLATE_ID must be set when SMS_PROVIDER is 'spug'"

    # Passkey RP ID 校验：设置了但无效则给出警告，passkey 功能将不可用
    _rp_id = (cfg.get("PASSKEY_RP_ID") or "").strip()
    if _rp_id and not is_passkey_enabled(_rp_id):
        import warnings

        warnings.warn(
            f"PASSKEY_RP_ID '{_rp_id}' is not a valid domain; "
            "passkey feature will be disabled. "
            "Set it to 'localhost' (dev) or a real domain like 'example.com'."
        )

    # 登录安全配置校验
    _fail_max = cfg["LOGIN_FAIL_MAX"]
    assert (
        isinstance(_fail_max, int) and _fail_max >= 1
    ), "LOGIN_FAIL_MAX must be a positive integer"
    _lock_time = cfg["LOGIN_LOCK_TIME"]
    assert (
        isinstance(_lock_time, int) and _lock_time >= 1
    ), "LOGIN_LOCK_TIME must be a positive integer"
    _ip_limit = cfg["LOGIN_IP_LIMIT"]
    assert (
        isinstance(_ip_limit, int) and _ip_limit >= 1
    ), "LOGIN_IP_LIMIT must be a positive integer"
    _ip_window = cfg["LOGIN_IP_WINDOW"]
    assert (
        isinstance(_ip_window, int) and _ip_window >= 1
    ), "LOGIN_IP_WINDOW must be a positive integer"

    # Prometheus Metrics 配置校验
    assert isinstance(cfg["METRICS_ENABLED"], bool), "METRICS_ENABLED must be a boolean"
    _metrics_path = cfg["METRICS_PATH"]
    assert isinstance(_metrics_path, str) and _metrics_path.startswith(
        "/"
    ), "METRICS_PATH must be a string starting with /"
    _cache_ttl = cfg["METRICS_CACHE_TTL"]
    assert (
        isinstance(_cache_ttl, int) and _cache_ttl >= 1
    ), "METRICS_CACHE_TTL must be a positive integer"

    # NOTICE 校验：list（公告列表）或 str（接口 URL）
    assert isinstance(
        cfg["NOTICE"], (list, str)
    ), "NOTICE must be a list or a URL string"

    # 字符串类配置校验
    for _key in (
        "SITE_ICP",
        "SITE_TITLE",
        "SITE_DESC",
        "SITE_KEYWORDS",
        "SITE_FAVICON",
        "SITE_LOGO",
        "HOST",
        "OIDC_INTERNAL_CLIENTS",
        "METRICS_TOKEN",
    ):
        assert isinstance(cfg[_key], str), f"{_key} must be a string"

    # 布尔类配置校验
    assert isinstance(cfg["SITE_PRIVACY"], bool), "SITE_PRIVACY must be a boolean"


config = FlaskConfig(APP_DIR)
config.from_object(ProdConfig if is_prod() else DevConfig)
config.from_envvar(ENV_NAME, silent=True)
config.from_prefixed_env(prefix=ENV_PREFIX)
PinConfig.apply(config)
_check_config_value(config)
