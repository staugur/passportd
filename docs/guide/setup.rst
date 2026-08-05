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
     - secret...
     - Flask session、cookie / JWT HMAC 签名密钥，至少14位，32位以上
   * - ``BASE_DIR``
     - str
     - ``APP_DIR``
     - 数据根目录；以下路径均固定从此派生（由 PinConfig 管理，不可覆盖）：
       
       * ``BASE_DIR/data`` — 数据目录（RSA 密钥、SQLite 数据库）
       * ``BASE_DIR/uploads`` — 本地上传目录
       * ``BASE_DIR/logs`` — 日志目录
       
       容器环境设为 ``/app``
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
     - 日志文件名，设置后写入 ``BASE_DIR/logs/`` 子目录
   * - ``URI_PREFIX``
     - str
     - ``/``
     - 全局 URL 前缀
   * - ``ICP``
     - str
     - ``""``
     - ICP 备案号，显示在页脚，为空则不显示

.. tip::

   ``BASE_DIR`` 是数据管理的核心配置项。设置后，以下路径由 ``PinConfig`` 固定派生，**不可通过环境变量覆盖**：

   - ``BASE_DIR/data`` — 数据目录（RSA 密钥、SQLite 数据库默认存放于此）
   - ``BASE_DIR/uploads`` — 本地上传目录
   - ``BASE_DIR/logs`` — 日志文件目录（``LOG_FILE`` 设置后写入此目录）

   ``DB_URI`` （SQLite 模式）中的 ``APP_DIR`` 也会自动替换为 ``BASE_DIR``。

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

OpenID Connect 配置
--------------------

OIDC 相关的以下值由 ``PinConfig`` 固定管理，不可通过配置或环境变量更改：

- ``OIDC_RSA_KEY_SIZE`` = ``4096``
- ``OIDC_RSA_PUBLIC_KEY`` → ``BASE_DIR/data/public.pem``
- ``OIDC_RSA_PRIVATE_KEY`` → ``BASE_DIR/data/private.key``

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
     - 邮件服务：空（不发送） / ``smtp`` / ``spug``
   * - ``SMTP_USER_MAIL``
     - str
     - ``""``
     - SMTP 发件邮箱，EMAIL_PROVIDER 为 ``smtp`` 时必填
   * - ``SMTP_USER_PASSWD``
     - str
     - ``""``
     - SMTP 邮箱密码，EMAIL_PROVIDER 为 ``smtp`` 时必填
   * - ``SMTP_SERVER``
     - str
     - ``""``
     - SMTP 服务器地址，EMAIL_PROVIDER 为 ``smtp`` 时必填
   * - ``SMTP_PORT``
     - int
     - ``587``
     - SMTP 端口，465=隐式SSL，其他=STARTTLS，25端口禁止使用
   * - ``SPUG_MAIL_TEMPLATE_ID``
     - str
     - ``""``
     - Spug 推送助手邮件模板编码，EMAIL_PROVIDER 为 ``spug`` 时必填

短信配置
---------

.. list-table::
   :header-rows: 1

   * - 配置项
     - 类型
     - 默认值
     - 说明
   * - ``SMS_PROVIDER``
     - str
     - ``""``
     - 短信服务：空（不发送） / ``spug``
   * - ``SPUG_SMS_TEMPLATE_ID``
     - str
     - ``""``
     - Spug 推送助手短信模板 ID，SMS_PROVIDER 为 ``spug`` 时必填

**SPUG_MAIL_TEMPLATE_ID 与 SPUG_SMS_TEMPLATE_ID 获取方法**：

Spug 推送助手提供官方验证码模板，无需自主创建。获取步骤：

1. 打开 `push.spug.cc <https://push.spug.cc>`_，微信扫码登录。
2. 进入验证码模板页面：

   - **短信验证码**：`push.spug.cc/console/verification/sms <https://push.spug.cc/console/verification/sms>`_
   - **邮件验证码**：`push.spug.cc/console/verification/mail <https://push.spug.cc/console/verification/mail>`_

3. 选择对应模板：

   - **短信验证码**：选择支持 ``${code}`` + ``${minute}`` 双参数的模板（另一个仅支持 ``${code}`` 单参数）。
   - **邮件验证码**：选择中文版模板（英/中两版参数相同，均含 ``${code}``、``${scene}``、``${minute}``）。

4. 复制模板编码（形如 ``Vf7Jp2sD9xL``），即为对应的 ``SPUG_MAIL_TEMPLATE_ID`` 或 ``SPUG_SMS_TEMPLATE_ID``。

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
   * - ``WEIBO_CLIENT_ID``
     - str
     - 微博 OAuth2 Client ID
   * - ``WEIBO_CLIENT_SECRET``
     - str
     - 微博 OAuth2 Client Secret
   * - ``QQ_CLIENT_ID``
     - str
     - QQ OAuth2 Client ID
   * - ``QQ_CLIENT_SECRET``
     - str
     - QQ OAuth2 Client Secret

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
   * - ``LOG_FILE``
     - stdout
     - ``sys.log``
     - 生产环境自动写入 ``BASE_DIR/logs/sys.log``
   * - ``NO_DAEMON``
     - N/A
     - ``False``
     - gunicorn 守护进程模式，默认后台运行（``False``），设置为 ``True`` 后前台运行

生产环境部署示例
-----------------

.. code-block:: shell

    export PASSPORT_ENV=production
    export PASSPORT_BASE_DIR="/app"
    export PASSPORT_DB_URI="mysql+pool://root:pwd@localhost:3306/passport?max_connections=30"
    export PASSPORT_REDIS_URI="redis://:pwd@localhost:6379/0"
    export PASSPORT_LOG_LEVEL="INFO"
    export PASSPORT_SECRET_KEY="your-secret-key-here"

    passportd start

.. warning::

    生产环境务必设置一个安全的 ``PASSPORT_SECRET_KEY``，该密钥用于 JWT
    HMAC-SHA256 签名 和 Cookie 登录状态。
