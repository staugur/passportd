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
   * - ``SITE_ICP``
     - str
     - ``""``
     - ICP 备案号，显示在页脚，为空则不显示。环境变量 ``PASSPORT_SITE_ICP``
   * - ``SITE_TITLE``
     - str
     - ``"Passport"``
     - 站点标题，用于浏览器标题、导航栏品牌、页脚版权等，为空回退 ``"Passport"``
   * - ``SITE_DESC``
     - str
     - ``""``
     - 站点描述，用于 meta description（SEO），为空不输出
   * - ``SITE_KEYWORDS``
     - str
     - ``""``
     - 站点关键词，英文逗号分隔，用于 meta keywords（SEO），为空不输出
   * - ``SITE_FAVICON``
     - str
     - ``""``
     - 站点 favicon 地址（URL 或静态资源路径），为空使用默认静态图标
   * - ``SITE_LOGO``
     - str
     - ``""``
     - 站点 logo 图片地址（URL），为空导航栏显示 ``SITE_TITLE`` 文字
   * - ``SITE_PRIVACY``
     - bool
     - ``False``
     - 是否启用隐私政策页面（``/privacy``），为 ``True`` 时页脚显示「隐私政策」链接。环境变量 ``PASSPORT_SITE_PRIVACY``（布尔，取值 ``true``/``false``）
   * - ``METRICS_ENABLED``
     - bool
     - ``True``
     - 是否启用 Prometheus 指标采集，关闭后 ``/metrics`` 返回 503
   * - ``METRICS_PATH``
     - str
     - ``/metrics``
     - Prometheus 指标端点路径（相对 ``URI_PREFIX``）
   * - ``METRICS_CACHE_TTL``
     - int
     - ``30``
     - 进程/业务/Redis 指标缓存秒数（秒）
   * - ``METRICS_TOKEN``
     - str
     - ``""``
     - 可选 Bearer Token 鉴权，Prometheus 抓取需携带 ``Authorization: Bearer <token>``

   Prometheus 抓取配置示例（已启用 ``METRICS_TOKEN`` 时）：

   .. code-block:: yaml

    scrape_configs:
      - job_name: "passportd"
        metrics_path: /metrics
        scheme: https
        bearer_token: "<METRICS_TOKEN>"
        static_configs:
          - targets: ["auth.example.com:10030"]

   Grafana 可视化：项目提供完整监控面板 ``examples/grafana_dashboard.json``，导入 Grafana 后选择 Prometheus 数据源即可查看进程资源、Gunicorn、Python GC、业务指标、Redis 与 HTTP 请求等全部指标。

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
     - ``465``
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
   * - ``LOGIN_FAIL_MAX``
     - int
     - ``5``
     - 同一账号连续密码错误达到该次数后临时锁定。环境变量 ``PASSPORT_LOGIN_FAIL_MAX``
   * - ``LOGIN_LOCK_TIME``
     - int
     - ``900``
     - 账号临时锁定时间（秒），到期自动解锁。环境变量 ``PASSPORT_LOGIN_LOCK_TIME``
   * - ``LOGIN_IP_LIMIT``
     - int
     - ``20``
     - 同一 IP 在窗口时间内允许的最大登录/注册/验证码请求次数。环境变量 ``PASSPORT_LOGIN_IP_LIMIT``
   * - ``LOGIN_IP_WINDOW``
     - int
     - ``60``
     - IP 限流统计窗口（秒）。环境变量 ``PASSPORT_LOGIN_IP_WINDOW``

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
   * - ``GITHUB_CALLBACK_PROXY`` (可选)
     - str
     - Github OAuth2 回调时代理地址。
       服务器无法直连 Github API时使用，
       如 ``http://proxy:8080``。仅支持 HTTP 代理。
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
   * - ``GOOGLE_CLIENT_ID``
     - str
     - Google OAuth2 Client ID
   * - ``GOOGLE_CLIENT_SECRET``
     - str
     - Google OAuth2 Client Secret
   * - ``GOOGLE_CALLBACK_PROXY`` (可选)
     - str
     - Google OAuth2 回调时代理地址。
       服务器无法直连 Google API（googleapis.com）时使用，
       如 ``http://proxy:8080``。仅支持 HTTP 代理。

OIDC 内部客户端配置
--------------------

passportd 作为统一认证中心时，平台角色（小写 ``admin`` / ``superadmin`` /
``user`` ）默认 **不向任何客户端输出** ，第三方应用的角色应由其自身基于 ``sub`` 管理。若自有项目
（自家应用）需要通过 OIDC 判定用户是否为管理员，可将应用加入内部客户端列表，
这些应用在申请 ``role`` scope 时可获得平台角色。

.. list-table::
   :header-rows: 1

   * - 配置项
     - 类型
     - 默认值
     - 说明
   * - ``OIDC_INTERNAL_CLIENTS``
     - str
     - ``""``
     - 内部（自家）客户端 name 列表，英文逗号分隔（容忍逗号两侧空格）。
       仅列表内的应用在 ``role`` scope 时返回用户平台角色，
       第三方客户端一律不返回。环境变量示例
       ``PASSPORT_OIDC_INTERNAL_CLIENTS="my-app, your-app"``。

.. note::

   内部客户端拿到的 ``role`` 仅为平台内置角色（小写 ``admin`` / ``superadmin`` /
   ``user``），配置在 ``ClientName:Role`` 格式的客户端角色会被过滤，
   不会泄露给其他客户端。

.. note::

   前端创建/编辑 OIDC 客户端的表单 **不展示** ``role`` 授权范围选项（对第三方
   不可见）。内部客户端需要 ``role`` scope 时，通过 OIDC 客户端 API 或数据库
   直接配置即可；后端在 ID Token 与 ``/oidc/userinfo`` 中仍按 ``OIDC_INTERNAL_CLIENTS``
   判断是否返回平台角色。编辑已带 ``role`` scope 的内部客户端时，前端会自动
   保留该 scope，不会因表单不显示而被误删。

Passkey（WebAuthn）配置
--------------------------

Passkey 基于 **WebAuthn** 标准，允许用户使用设备生物识别（指纹/面容）或 PIN 码
进行无密码登录。配置 ``PASSKEY_RP_ID`` 为有效域名即可启用。

.. list-table::
   :header-rows: 1

   * - 配置项
     - 类型
     - 默认值
     - 说明
   * - ``PASSKEY_RP_ID``
     - str
     - ``""``
     - Relying Party ID，即当前服务的域名（不含协议和端口）。
       设置为有效域名后 Passkey 功能自动启用；为空或无效值时禁用。

       示例：

       - 开发环境：``localhost(默认)``
       - 生产环境：``auth.example.com``

       注意：RP ID 必须是浏览器地址栏中的注册域名（或子域名），
       **不支持 IP 地址**。

.. tip::

   Passkey 遵循 WebAuthn 规范，要求如下：

   - **HTTPS**：生产环境必须使用 HTTPS（``localhost`` 例外）。
   - **RP ID 一致性**：前端注册/登录时浏览器提供的 ``rp.id`` 必须与
     ``PASSKEY_RP_ID`` 完全一致，否则验证会失败。
   - **RP Name**：固定为 ``passportd``，在浏览器密钥管理界面展示。
   - **Challenge 有效期**：每次注册/登录 generated challenge 缓存 300 秒，
     超时需要重新发起。

   服务端未启用时（``PASSKEY_RP_ID`` 为空或无效），前端登录页和个人中心
   的 Passkey 入口会自动隐藏。

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
