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
    SqliteDatabase,
)
from playhouse.db_url import connect

from ..basis.conf import config
from ..utils.common import now

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
    #: 地区
    location = CharField(default="")
    #: 本地账号密码哈希（第三方用户为 NULL）
    password_hash = CharField(max_length=256, null=True)
    #: 生成时间戳与修改资料时间戳
    ctime = IntegerField(default=now)
    mtime = IntegerField(default=0)
    #: 用户状态 0是禁用 1是启用
    status = IntegerField(default=1)
    #: User Roles (split by space), support: Admin/User(Self), [Client]:Admin/User/Other(Third OAuth Client), and SuperAdmin(Admin for All)
    role = CharField(default="User")

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
    #: - 本地化: username mobile email
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


# Create tables if they don't exist
with db.atomic():
    db.create_tables(
        [User, Auth, OAuthClient, OAuthToken, OAuthAuthorization, LoginRecord],
        safe=True,
    )
