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

from urllib.parse import urlparse

from peewee import (
    Database,
    Model,
    CharField,
    IntegerField,
    TextField,
    BlobField,
    SqliteDatabase,
)
from playhouse.db_url import connect

from ..basis.conf import config
from ..utils.common import logger, now

_db_uri = config["DB_URI"]
if _db_uri.startswith("sqlite"):
    # SQLite 不使用连接池：SQLite 是文件型数据库，池化无益且会导致
    # Flask 多线程模式下 MaxConnectionsExceeded。
    _db_path = urlparse(_db_uri).path
    db: Database = SqliteDatabase(
        _db_path,
        pragmas={
            "journal_mode": "wal",  # WAL 模式：读写并发不互斥
            "cache_size": -1024 * 64,  # 64MB 缓存
            "foreign_keys": 1,
        },
    )
    db.connect_params["check_same_thread"] = False
else:
    db: Database = connect(_db_uri, prefer_psycopg3=True)


class User(Model):
    """用户基本资料，uid唯一标识用户，每个用户有至少一种认证方式"""

    uid = CharField(max_length=22, unique=True, index=True)
    #: 昵称
    nickname = CharField(default="")
    #: 简介
    bio = TextField(default="")
    #: 性别 0是女 1是男 2是未知
    gender = IntegerField(default=2)
    #: 头像
    avatar = CharField(default="")
    #: 自定义背景图 URL
    background_image = CharField(default="")
    #: 地区
    location = CharField(default="")
    #: 本地账号密码哈希（第三方用户为 NULL）
    password_hash = CharField(max_length=256, null=True)
    #: 生成时间戳与修改资料时间戳
    ctime = IntegerField(default=now)
    mtime = IntegerField(default=0)
    #: 用户状态 0是禁用 1是启用
    status = IntegerField(default=1)
    #: User Roles (split by space), for internal project;
    #: Support: admin/user(Self), [client]:admin/user/other, and superadmin(admin for All)
    role = CharField(default="user")

    class Meta:
        database = db
        table_name = "passport_user"


class Auth(Model):
    """登录方式，本地化或第三方社会化账号绑定"""

    #: 对应 User 表的 uid 字段，可能有多条记录，即多种登录方式
    uid = CharField(max_length=22, index=True)
    #: 用户名、手机号、邮箱或第三方应用的账号（根据"第三方名称.third_name"构建）
    account = CharField(max_length=256, unique=True, index=True)
    #: 第三方应用的唯一标识(id、openid、union_id)
    tpid = CharField(max_length=256, null=True)
    #: 注册类型
    #: - 本地化: username mobile email(后两者验证通过后方可入库，可用于登录和找回密码)
    #: - 第三方: 3rd(如github qq weibo)
    classify = CharField(max_length=15)
    #: 生成时间戳与更新时间戳
    ctime = IntegerField(default=now)
    mtime = IntegerField(default=0)

    class Meta:
        database = db
        table_name = "passport_auth"


class OAuthClient(Model):
    """OpenID Connect 第三方应用"""

    #: 对应 User 表的 uid 字段，可能有多条记录，即所属用户
    uid = CharField(max_length=22, index=True)
    #: 唯一标识名
    name = CharField(max_length=50, unique=True, index=True)
    #: 主页
    homepage = CharField(default="")
    #: 简介
    bio = TextField(default="")
    #: 客户端标识和密钥以及回调地址
    client_id = CharField(max_length=24, index=True)
    client_secret = CharField(max_length=48)
    redirect_uri = TextField()
    #: 授权类型，支持 authorization_code
    grant_type = CharField(default="authorization_code")
    #: 响应类型，支持 code
    response_type = CharField(default="code")
    #: 授权列表（空格分开），支持 openid、profile
    scope = CharField(default="openid")
    #: 生成时间戳与更新时间戳
    ctime = IntegerField(default=now)
    mtime = IntegerField(default=0)

    class Meta:
        database = db
        table_name = "passport_oauth_client"


class OAuthToken(Model):
    """OpenID Connect 颁发的令牌"""

    #: 对应 User 表的 uid 字段，可能有多条记录，即所属用户
    uid = CharField(max_length=22, index=True)
    #: 所属客户端
    client_id = CharField(max_length=24, index=True)
    token_type = CharField(default="Bearer")
    #: 访问令牌和刷新令牌，唯一标识
    access_token = CharField(max_length=255, unique=True)
    #: 访问令牌过期时间（秒）
    expires_in = IntegerField()
    #: 授权列表（空格分开），支持 openid、profile
    scope = CharField()
    #: 生成时间戳
    ctime = IntegerField(default=now)
    #: Token 状态， 1是有效，0是撤销
    status = IntegerField(default=1)
    #: 其他记录：IP地址
    ip = CharField(default="")
    #: 其他记录：用户代理
    ua = CharField(default="")

    class Meta:
        database = db
        table_name = "passport_oauth_token"


class OAuthAuthorization(Model):
    """OpenID Connect 授权记录（仅记录 approved 授权的用户）"""

    #: 授权用户 uid
    uid = CharField(max_length=22, index=True)
    #: 被授权的 OIDC Client
    client_id = CharField(max_length=24, index=True)
    #: 授权的 scope 范围（空格分开）
    scope = CharField()
    #: 授权时间戳
    ctime = IntegerField(default=now)
    #: 客户端 IP
    ip = CharField(default="")
    #: User-Agent
    ua = CharField(default="")

    class Meta:
        database = db
        table_name = "passport_oauth_authorization"


class LoginRecord(Model):
    """用户登录历史记录"""

    #: 用户 uid
    uid = CharField(max_length=22, index=True)
    #: 登录账号
    account = CharField(max_length=256, index=True)
    #: 登录方式：local / oauth2_github / oauth2_gitee / oauth2_qq / oauth2_weibo
    method = CharField(max_length=32)
    #: 客户端 IP
    ip = CharField(default="")
    #: 地理位置（城市/省份/国家）
    location = CharField(default="")
    #: 原始 User-Agent
    user_agent = TextField(default="")
    #: 浏览器名称
    browser = CharField(default="")
    #: 操作系统
    os = CharField(default="")
    #: 设备类型：Desktop / Mobile / Tablet / Unknown
    device = CharField(default="")
    #: 浏览器指纹哈希
    fingerprint = CharField(max_length=64, default="")
    #: 登录时间戳
    ctime = IntegerField(default=now)

    class Meta:
        database = db
        table_name = "passport_login_record"
        indexes = ((("uid", "ctime"), False),)  # 复合索引：按用户查询登录历史


class PasskeyCredential(Model):
    """WebAuthn Passkey 凭证，一个用户可绑定多个设备。"""

    #: 凭证 ID（base64url 编码，对应 WebAuthn credential_id）
    credential_id = CharField(max_length=512, unique=True, index=True)
    #: 所属用户 uid
    uid = CharField(max_length=22, index=True)
    #: 公钥（COSE 格式二进制，用于签名验证）
    public_key = BlobField()
    #: 签名计数器，用于防重放攻击，每次成功认证后 +1
    sign_count = IntegerField(default=0)
    #: 设备名称，如 "Chrome on macOS"，方便用户识别
    device_name = CharField(max_length=128, default="")
    #: 凭证类型：platform（平台认证器，如指纹/面容）或 cross-platform（跨平台，如 USB 密钥）
    credential_type = CharField(max_length=32, default="platform")
    #: 创建时间
    ctime = IntegerField(default=now)
    #: 最近使用时间
    last_used_at = IntegerField(default=0)

    class Meta:
        database = db
        table_name = "passport_passkey"


class AuditLog(Model):
    """用户安全审计日志，记录敏感操作（注册、绑定、解绑、Passkey、OIDC 客户端管理等）。"""

    #: 用户 uid
    uid = CharField(max_length=22, index=True)
    #: 操作类型：register / bind_account / unbind_account / passkey_add / passkey_delete
    #:          / oidc_client_create / oidc_client_update / oidc_client_delete / oidc_auth_revoke
    #:          / change_password / account_delete
    action = CharField(max_length=32)
    #: 操作详情（JSON 字符串，包含相关参数如 account、provider、client_id 等）
    detail = TextField(default="")
    #: 客户端 IP
    ip = CharField(default="")
    #: User-Agent
    user_agent = TextField(default="")
    #: 操作时间戳
    ctime = IntegerField(default=now)

    class Meta:
        database = db
        table_name = "passport_audit_log"
        indexes = ((("uid", "ctime"), False),)


class UserSession(Model):
    """用户活跃会话记录。

    每次登录成功时创建一条会话，登出或注销时删除。
    用于安全页面展示活跃会话列表（设备、IP、地理位置、浏览器、登录时间）。
    """

    #: 用户 uid
    uid = CharField(max_length=22, index=True)
    #: 会话标识（随机 token）
    session_key = CharField(max_length=64, unique=True, index=True)
    #: 客户端 IP
    ip = CharField(max_length=64, default="")
    #: 地理位置（通过 IP 查询获得）
    location = CharField(max_length=128, default="")
    #: 原始 User-Agent 字符串
    user_agent = TextField(default="")
    #: 浏览器名称
    browser = CharField(max_length=64, default="")
    #: 操作系统
    os = CharField(max_length=64, default="")
    #: 设备类型
    device = CharField(max_length=32, default="")
    #: 登录来源（local/vcode/passkey/oauth2_github 等）
    method = CharField(max_length=32, default="")
    #: 登录发起方（self 表示直接登录，OIDC 客户端名称表示通过 SSO 跳转登录）
    source = CharField(max_length=64, default="")
    #: 登录时间戳
    ctime = IntegerField(default=now)
    #: 会话过期时间戳（对应 JWT exp）
    expire_time = IntegerField()

    class Meta:
        database = db
        table_name = "passport_user_session"
        indexes = ((("uid", "ctime"), False),)


def init_db() -> None:
    """初始化数据库表结构（幂等），在应用启动时调用。

    模块导入时不建表，避免 import 副作用；仅在真正创建应用时执行。
    对已存在的表，补充缺失的新列（轻量迁移）。
    """
    with db.atomic():
        db.create_tables(
            [
                User,
                Auth,
                OAuthClient,
                OAuthToken,
                OAuthAuthorization,
                LoginRecord,
                PasskeyCredential,
                AuditLog,
                UserSession,
            ],
            safe=True,
        )
        # 轻量迁移：为已存在的表补充新列（仅执行一次，幂等）
        _ensure_column(
            User._meta.table_name,
            "background_image",
            "VARCHAR(255) NOT NULL DEFAULT ''",
        )


def _ensure_column(table_name: str, column: str, definition: str) -> None:
    """若表中不存在指定列则 ALTER TABLE 添加（SQLite/MySQL/PostgreSQL 通用）。"""
    try:
        existing = {c.name for c in db.get_columns(table_name)}
    except Exception as exc:  # noqa: BLE001
        # 表不存在等情况直接跳过，交给 create_tables 处理
        logger.debug("init_db: 检查表 %s 列结构失败，跳过: %s", table_name, exc)
        return
    if column not in existing:
        try:
            db.execute_sql(
                'ALTER TABLE "{}" ADD COLUMN "{}" {}'.format(
                    table_name, column, definition
                )
            )
            logger.info("init_db: 已为表 %s 补充新列 %s", table_name, column)
        except Exception as exc:  # noqa: BLE001
            # 并发建列等竞态下忽略，确保幂等；记录日志便于排查
            logger.warning(
                "init_db: 为表 %s 添加列 %s 失败: %s", table_name, column, exc
            )



