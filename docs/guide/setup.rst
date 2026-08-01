.. _setup:

配置说明
========

passportd 使用 Flask 的配置体系，所有配置项定义在 :mod:`passportd.basis.conf` 中，
支持通过环境变量或配置文件进行覆盖。

配置加载顺序
-------------

1. ``BaseConfig`` —— 默认配置（适用于开发环境）
2. ``DevConfig`` / ``ProdConfig`` —— 根据 ``PASSPORT_ENV`` 环境变量选择
3. ``PASSPORT_CONFIG`` 环境变量指定的配置文件
4. ``PASSPORT_`` 前缀的环境变量（自动映射，如 ``PASSPORT_HOST`` → ``HOST``）

全局配置
---------

.. list-table::
   :header-rows: 1

   * - 配置项
     - 类型
     - 默认值
     - 说明
   * - ``HOST``
     - str
     - ``0.0.0.0``
     - 监听地址
   * - ``PORT``
     - int
     - ``10030``
     - 监听端口
   * - ``ENV``
     - str
     - ``development``
     - 运行环境：``development`` / ``production``
   * - ``SECRET_KEY``
     - str
     - 自动生成
     - Flask session / JWT HMAC 签名密钥
   * - ``DB_URI``
     - str
     - ``sqlite://...``
     - 数据库连接串（支持 SQLite / MySQL / PostgreSQL，MySQL/PostgreSQL 使用 +pool 连接池）
   * - ``REDIS_URI``
     - str
     - ``redis://...``
     - Redis 连接串
   * - ``LOG_LEVEL``
     - str
     - ``DEBUG``
     - 日志级别（DEBUG / INFO / WARNING / ERROR / CRITICAL）
   * - ``LOG_FILE``
     - str
     - ``None``
     - 日志文件名，不设置则输出到 stdout
   * - ``LOG_DIR``
     - str
     - ``None``
     - 日志文件目录
   * - ``URI_PREFIX``
     - str
     - ``/``
     - 全局 URL 前缀
   * - ``TRUST_PROXY``
     - bool
     - ``True``
     - 是否信任代理头，从 ``X-Forwarded-For`` 和 ``X-Real-IP`` 获取客户端 IP

数据库配置
----------

passportd 支持三种数据库后端，通过 ``DB_URI`` 配置：

**SQLite（默认）**：

.. code-block:: shell

    export PASSPORT_DB_URI="sqlite:///tmp/passport.db"

**MySQL**：

.. code-block:: shell

    export PASSPORT_DB_URI="mysql+pool://root:pwd@localhost:3306/passport?max_connections=20"

**PostgreSQL**：

.. code-block:: shell

    export PASSPORT_DB_URI="psycopg3+pool://postgres:pwd@localhost:5432/passport?max_connections=20"

.. note::

    MySQL 和 PostgreSQL 驱动需要额外安装：``pip install passportd[mysql]`` 或 ``pip install passportd[pgsql]``

OpenID Connect 配置
--------------------

.. list-table::
   :header-rows: 1

   * - 配置项
     - 类型
     - 默认值
     - 说明
   * - ``OIDC_RSA_PUBLIC_KEY``
     - str
     - ``data/public.pem``
     - RSA 公钥文件路径
   * - ``OIDC_RSA_PRIVATE_KEY``
     - str
     - ``data/private.key``
     - RSA 私钥文件路径
   * - ``OIDC_RSA_KEY_SIZE``
     - int
     - ``2048``
     - RSA 密钥长度（生产环境 4096）
   * - ``OAUTH2_TOKEN_EXPIRES_IN``
     - dict
     - ``{"authorization_code": 86400}``
     - Token 过期时间配置（秒）

上传配置
---------

.. list-table::
   :header-rows: 1

   * - 配置项
     - 类型
     - 默认值
     - 说明
   * - ``UPLOAD_METHOD``
     - str
     - ``local``
     - 上传方式：``local`` 本地存储 / ``sapic`` Sapic 图床
   * - ``SAPIC_APIURL``
     - str
     - ``https://sapicd.com``
     - Sapic API 地址
   * - ``SAPIC_LINKTOKEN``
     - str
     - ``""``
     - Sapic LinkToken
   * - ``LOCAL_UPLOAD_FOLDER``
     - str
     - ``uploads/``
     - 本地上传目录

邮件配置
---------

.. list-table::
   :header-rows: 1

   * - 配置项
     - 类型
     - 默认值
     - 说明
   * - ``EMAIL_PROVIDER``
     - str
     - ``""``
     - 邮件服务：空（不发送） / ``smtp`` / ``sendcloud``
   * - ``SMTP_USER_MAIL``
     - str
     - ``""``
     - SMTP 发件邮箱
   * - ``SMTP_USER_PASSWD``
     - str
     - ``""``
     - SMTP 邮箱密码
   * - ``SMTP_SERVER``
     - str
     - ``""``
     - SMTP 服务器地址
   * - ``SMTP_PORT``
     - int
     - ``587``
     - SMTP 端口（SSL）
   * - ``SENDCLOUD_API_USER``
     - str
     - ``""``
     - SendCloud API 用户
   * - ``SENDCLOUD_API_KEY``
     - str
     - ``""``
     - SendCloud API Key
   * - ``SENDCLOUD_MAIL_FROM``
     - str
     - ``""``
     - SendCloud 发件地址

OAuth2 第三方登录配置
----------------------

.. list-table::
   :header-rows: 1

   * - 配置项
     - 类型
     - 说明
   * - ``GITHUB_CLIENT_ID``
     - str
     - GitHub OAuth App Client ID
   * - ``GITHUB_CLIENT_SECRET``
     - str
     - GitHub OAuth App Client Secret
   * - ``GITEE_CLIENT_ID``
     - str
     - Gitee OAuth App Client ID
   * - ``GITEE_CLIENT_SECRET``
     - str
     - Gitee OAuth App Client Secret

生产环境配置
-------------

设置 ``PASSPORT_ENV=production`` 启用生产环境配置 ``ProdConfig``，主要差异：

.. list-table::
   :header-rows: 1

   * - 配置项
     - 开发环境
     - 生产环境
     - 说明
   * - ``LOG_LEVEL``
     - ``DEBUG``
     - ``INFO``
     - 日志级别
   * - 日志输出
     - stdout
     - 文件（按日期滚动）
     - 日志存储方式
   * - ``OIDC_RSA_KEY_SIZE``
     - ``2048``
     - ``4096``
     - RSA 密钥长度
   * - ``NO_DAEMON``
     - N/A
     - ``False``
     - gunicorn 守护进程模式，默认后台运行（``False``），设置为 ``True`` 后前台运行

生产环境部署示例
-----------------

.. code-block:: shell

    export PASSPORT_ENV=production
    export PASSPORT_DB_URI="mysql+pool://root:pwd@localhost:3306/passport?max_connections=30"
    export PASSPORT_REDIS_URI="redis://:pwd@localhost:6379/0"
    export PASSPORT_LOG_LEVEL="INFO"
    export PASSPORT_SECRET_KEY="your-secret-key-here"

    passportd start

.. warning::

    生产环境务必设置一个安全的 ``PASSPORT_SECRET_KEY``，该密钥用于 JWT
    HMAC-SHA256 签名。
