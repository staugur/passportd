更新日志
========

v2.7.0
------

新特性
~~~~~~

- 新增站点配置：``SITE_TITLE``（站点标题）、``SITE_DESC``（meta description）、``SITE_KEYWORDS``（meta keywords）、``SITE_FAVICON``（favicon 地址）、``SITE_LOGO``（导航栏 logo 图片）。站点标题用于浏览器标题、导航栏品牌、页脚版权等（为空回退 ``"Passport"``），favicon/logo 为空时分别回退默认静态图标与文字品牌。新增 Prometheus 指标采集与导出：默认 ``GET /metrics`` 端点，覆盖以下指标类别：
- 新增 Grafana Dashboard 配置示例 ``examples/grafana_dashboard.json``：覆盖进程资源、Gunicorn、Python/GC、业务指标、Redis、HTTP 请求等全部指标面板，导入 Grafana 后选择 Prometheus 数据源即可使用。
- 新增 CLI ``role`` 子命令组，用于管理用户角色：
- 登录安全：新增暴力破解防护。同一账号连续密码错误 ``LOGIN_FAIL_MAX`` 次（默认 5）后锁定 ``LOGIN_LOCK_TIME`` 秒（默认 900），锁定期间拒绝密码登录并提示剩余锁定时间；同一 IP 在 ``LOGIN_IP_WINDOW`` 秒（默认 60）内超过 ``LOGIN_IP_LIMIT`` 次（默认 20）登录/注册/验证码请求时全局限流。空账号/空密码不计入失败统计，登录成功自动清除失败计数并解除锁定。新增错误码 ``ACCOUNT_LOCKED``（前端 ``ERROR_ZH`` 已映射中文），覆盖密码登录、验证码登录、注册及验证码发送接口。
- 配置校验：``_check_config_value`` 启动校验范围扩展到 ``LOGIN_*``（正整数）、``METRICS_ENABLED``（布尔，避免环境变量字符串 ``"false"`` 被当作真值）、``METRICS_PATH``（以 ``/`` 开头）、``METRICS_CACHE_TTL``（正整数）、``LOG_LEVEL``（合法日志级别）、``NOTICE``（list 或 URL 字符串）及 ``SITE_*``/``HOST``/``OIDC_INTERNAL_CLIENTS``/``METRICS_TOKEN``（字符串），非法配置在启动时直接报错。

变更
~~~~

- API 错误响应统一语言与本地化：``ApiError`` 新增 ``code`` 错误码字段，``to_dict()`` 返回 ``{"success": false, "code": "...", "message": "..."}``；所有 API 抛错消息统一为英文，前端通过 ``ERROR_ZH`` 映射表将错误码翻译为中文文案（未映射时回退显示英文 ``message``）。涉及注册、登录、验证码、绑定/解绑、改密、注销、OIDC 客户端、Passkey 等全部接口。
- 前端创建/编辑 OIDC 客户端表单不再展示 ``role`` 授权范围选项（第三方不可见）。后端逻辑不变：内部客户端仍可通过 API / 数据库配置 ``role`` scope，ID Token 与 ``/oidc/userinfo`` 按内部客户端判断照常返回平台角色；编辑已带 ``role`` scope 的内部客户端时前端自动保留该 scope，避免误删。
- OIDC 平台角色按客户端隔离输出：新增配置 ``OIDC_INTERNAL_CLIENTS``（默认 ``""``），为内部（自家）客户端 name 列表，英文逗号分隔（容忍逗号两侧空格）。仅列表内的应用在申请 ``role`` scope 时可获得用户平台角色（小写 ``admin``/``superadmin``/``user``），并自动过滤 ``ClientName:Role`` 格式的客户端角色；第三方客户端一律不再输出平台角色，避免全局角色泄露给非可信应用。ID Token 与 ``/oidc/userinfo`` 均生效。环境变量示例 ``PASSPORT_OIDC_INTERNAL_CLIENTS="my-app, your-app"``。
- 内置角色统一为小写存储（``admin``/``superadmin``/``user``），其他格式仅支持客户端角色（``ClientName:Role``），由 ``is_valid_user_role`` 校验，其中 ``ClientName`` 需通过 ``appname_check``（小写字母开头、4-33 位小写字母/数字/下划线/连字符）。CLI 输入内置角色时自动转为小写（大写 ``Admin``/``SuperAdmin`` 输入同样归一为小写）。
- 页脚 ICP 备案号配置项由 ``ICP`` 更名为 ``SITE_ICP``（站点配置统一命名前缀），环境变量同步为 ``PASSPORT_SITE_ICP``。

v2.6.5
------

修复
~~~~

- 修复 Google OAuth2 回调报 ``Failed to parse userinfo: 'sub'``：``userinfo_endpoint`` 配置为 v1 端点（``oauth2/v1/userinfo``），返回字段为 ``id``，但 ``parse_userinfo`` 取 ``userinfo["sub"]`` 导致 ``KeyError``。已将 ``userinfo_endpoint`` 和 ``api_base_url`` 升级到 v3 端点（``oauth2/v3/userinfo``），返回 ``sub`` 字段。同时 ``parse_userinfo`` 增加回退逻辑：优先取 ``sub``，兼容取 ``id``。
- 修复 OAuth2 首次登录选择「直接创建账号」报 ``Invalid account or credential``：``add_profile`` 中 ``check_credential_rule`` 校验密码长度 6~32 字符，但 OAuth2 回调传入的 ``credential`` 是 ``access_token``（通常远超 32 字符），导致校验失败。改为仅对本地账号校验密码规则，第三方账号跳过该检查。

v2.6.4
------

修复
~~~~

- 修复登录页面 ``signin.j2`` 中 ``{{ next }}`` 在 ``<script>`` 标签内被 Jinja2 ``autoescape`` 破坏的问题：URL 中的 ``&`` 被转义为 ``&amp;``，导致验证码/passkey 登录后跳转到 OIDC authorize 页面时 state 等查询参数解析错误。改用 ``|tojson`` 过滤器确保 JavaScript 上下文中字符串安全渲染。
- 修复 Passkey 登录成功后 ``sid`` Cookie 丢失导致后续 OIDC 授权流程抛 ``joserfc.errors.BadSignatureError`` 的问题：``passkey_login_verify`` 端点未调用 ``auto_set_user_state`` 设置 ``sid`` Cookie，仅通过 JSON 返回 JWT token，前端 JS 通过 ``document.cookie`` 设置 Cookie 丢失 ``httponly`` 和 ``secure`` 属性。现已将 ``passkey_login_verify`` 改为调用 ``auto_set_user_state``，由服务端 ``Set-Cookie`` 响应头正确设置登录态。同时清理前端 ``signin.j2`` 中冗余的 ``document.cookie`` 操作。
- 修复 Google OAuth2 登录报 ``Missing "jwks_uri" in metadata``：scope 含 ``openid`` 时 authlib 自动校验 id_token，需要 ``jwks_uri``。注册时补充 ``jwks_uri`` 和 ``userinfo_endpoint`` 元数据，并将 ``GOOGLE_CALLBACK_PROXY`` 代理注入 ``client_kwargs``，确保 JWKS 公钥拉取也走代理。

v2.6.3
------

修复：会话获取IP地点

更改：Flask-PluginKit更新版本。

v2.6.2
------

新特性
~~~~~~

- 活跃会话新增登录发起方记录：``UserSession`` 模型增加 ``source`` 字段，通过解析 OIDC authorize URL 中的 ``client_id`` 自动识别登录来源（``self`` 表示直接登录，OIDC 客户端名称表示通过 SSO 跳转登录）。

.. code-block:: sql

   ALTER TABLE passport_user_session ADD COLUMN source VARCHAR(64) NOT NULL DEFAULT '';

- 安全中心活跃会话列表展示登录方式（``method``）和登录来源（``source``）。

变更
~~~~

- 验证码登录 API 增加 ``next`` 参数传递，确保 vcode 登录也正确记录登录发起方。

v2.6.1
------

新特性
~~~~~~

- 活跃会话新增登录来源记录：``UserSession`` 模型增加 ``method`` 字段，区分 local/vcode/passkey/oauth2_github 等登录方式。

.. code-block:: sql

   ALTER TABLE passport_user_session ADD COLUMN method VARCHAR(32) NOT NULL DEFAULT '';

修复
~~~~

- 修复第三方 OAuth 登录（已绑定账号路径）未生成活跃会话的问题。
- 修复活跃会话地理位置始终为空的问题：``auto_set_user_state()`` 改用 ``get_ip()`` 提取真实客户端 IP，替代内网 ``remote_addr``。
- 修复 daemon 线程无异常处理导致会话信息更新静默失败的问题：``RecordLoginInterface`` 和 ``RecordSessionInterface`` 线程体增加 try/except 日志；``update_session_info()`` 增加 0 行匹配诊断日志。

变更
~~~~

- ``changelog.rst`` 从 ``docs/`` 移至项目根目录并重命名为 ``CHANGELOG.rst``，Sphinx 文档通过 ``.. include::`` 引用。


v2.6.0
------

新特性
~~~~~~

- 新增安全审计日志功能：独立 ``AuditLog`` 数据库模型，自动记录注册、绑定/解绑账号、Passkey 增删、OIDC 客户端增删改、OIDC 授权撤销等敏感操作；新增前端「安全」页面，用户可查看个人审计日志并按时间倒序浏览。
- 公告支持 ``closable`` 字段：设为 ``false`` 时公告不可关闭（适用于安全/维护类通知），默认 ``true`` 保持原有可关闭行为。
- 新增活跃会话管理：安全页面展示所有已登录设备，含设备/浏览器、IP（含地理位置）、登录时间，标识「当前设备」；登录时自动记录会话，登出/注销时自动清理。

变更
~~~~

- 「登录历史」从个人资料页移至安全页面，与活跃会话、审计日志统一展示。
- IP 地理位置查询接口 ``IP_API_URL`` 改为可配置，通过环境变量 ``PASSPORT_IP_API_URL`` 覆盖，默认值为 ``https://hub.saintic.com/openservice/ip/rest``。


v2.5.0
------

新特性
~~~~~~

- 新增账号注销功能：需密码验证且确认名下无 OIDC 客户端，级联删除用户所有数据（User/Auth/登录记录/OIDC 授权/Passkey 等），操作不可恢复。
- 新增 Google OAuth2 登录支持：配置 ``GOOGLE_CLIENT_ID`` 和 ``GOOGLE_CLIENT_SECRET`` 即可启用。

修复
~~~~

- 修复远程公告过滤失败的问题：API 返回 ``etime: null`` 时 .get() 未触发默认值导致全量被过滤。
- 修复邮箱账号无法解绑的问题：前端用 ``not loop.first`` 限制导致首个注册的邮箱无法显示解绑按钮。
- 新增第三方社交账号解绑功能：后端和前端均支持解绑第三方登录绑定。

v2.4.2
------

新特性
~~~~~~

- 新增公告通知功能：支持本地列表和远程 URL 两种配置方式，页面顶部轻量展示，支持浏览器级永久关闭。

修复
~~~~

- 修复 Spug 短信发送时缺少 ``number`` 变量的问题，导致提示「缺少变量 number 的值」。

v2.4.1
------

修复
~~~~

- 修复 get_ip 函数

变更
~~~~

- 验证码登录新增「记住登录（7天有效）」选项：勾选后 Cookie 有效期从 2 小时延长至 7 天，登录态 Cookie 改为服务端 httponly 设置（不再由前端 JS 写入）。

v2.4.0
------

新特性
~~~~~~~~

- **WebAuthn Passkey 支持**：用户可注册并使用 Passkey（指纹/面容/PIN 码）进行登录，彻底替代密码。
  - 前端新增 Passkey 登录入口（登录页）和 Passkey 设备管理（个人主页），服务端未启用时前端自动隐藏。

修复
~~~~

- 修复登录页面宽度过窄（420px → 480px），避免「密码登录 / 验证码登录 / Passkey 登录」三个 Tab 文字被截断。

变更
~~~~

- SMTP 默认端口从 587 改为 465：国内主流邮箱服务商（QQ/163/阿里/腾讯企业邮）均使用 465 端口（SSL 隐式加密），587（STARTTLS）在国内几乎不可用。

v2.3.0
------

新特性
~~~~~~~~

- **「我的授权」管理页面**：用户可在个人中心查看并撤销已授权的 OIDC 客户端，撤销时同步清除关联 Token。
- **绑定 / 解绑邮箱和手机号**：已登录用户可通过验证码绑定新邮箱或手机号，或解绑已有邮箱/手机号，验证不通过不执行操作。
- **短信验证码日频限制**：仅对手机号生效——每个手机号每天最多 10 次，全局每天最多 100 次。计数器存储在 Redis，按天自动过期。
- **头像上传与裁剪**：个人资料编辑页支持上传头像，集成 Cropper.js 进行裁剪（1:1 方形），裁剪后转为 JPEG 通过 ``/api/upload`` 上传，支持 local 和 SAPIC 两种存储后端。

修复
~~~~

- **OIDC 授权页面显示客户端名称**：修复授权页面显示的是 ``client_id`` 而非 ``client_name`` 的问题，新增 ``OIDCClient.client_name`` 属性。
- **多级代理环境获取真实 IP**：``get_ip()`` 改为优先读取 ``X-Real-IP``、其次 ``X-Forwarded-For`` 最左端，适配 WAF → easytier 等多级代理链路。

变更
~~~~

- 「我的授权」独立页面取消，内容合并至 OIDC Client 页面下方，仅显示最近 10 条授权记录。
- 验证码登录 method 标记由 ``local_vcode`` 简化为 ``vcode``。
- ``auto_create_data_dir()`` 改为接受路径参数，不再硬编码 ``APP_DIR/data``。
- 移除 Codecov 集成（``ci.yml`` 中删除上传步骤，``README.md`` 中删除 badge）。
- Dockerfile / kubernetes.yaml 中统一使用 ``PASSPORT_BASE_DIR=/app``。K8s 新增 ``passportd-data`` PVC 挂载 ``/app``。
- 解绑邮箱/手机号由验证码改为**密码确认**（更安全，符合行业惯例）。
- OIDC 客户端详情弹窗新增 Discovery 端点（``/.well-known/openid-configuration``）显示。
- 个人资料头像由手动输入 URL 改为**上传 + 裁剪**，集成 Cropper.js。

v2.2.0
------

精简配置项

v2.1.0
------

Spug Push 验证码集成、登录方式扩展及多项修复优化。

新特性
~~~~~~~~

- **验证码注册登录**：支持通过 SMTP / Spug Push 官方验证码模板发送邮件和短信。
- **ICP备案**：页脚新增ICP备案号显示。

修复
~~~~

- 修复 GitHub Actions sdist 构建失败（``MANIFEST.in`` 未包含 ``requirements/``）
- 修复 Sphinx 文档构建问题

变更
~~~~

- Redis key 统一 ``passportd:`` 前缀（``PROC_NAME`` 变量拼接，禁止硬编码）
- 修改密码功能更改。

v2.0.0
------

重大更新，完全重构 OIDC 模块。

新特性
~~~~~~~~

- 基于 Authlib 重构 OIDC 模块，完整支持 OpenID Connect 协议
- OAuth2 插件化架构，基于 Flask-PluginKit 实现动态加载
- 内置 GitHub 和 Gitee OAuth2 登录支持
- 支持 Authorization Code Grant 授权流程
- 支持 OIDC Discovery 端点 (``.well-known/openid-configuration``)
- 支持 JWKS 端点 (``/oidc/jwks``)，RS256 算法签名
- 支持用户信息端点 (``/oidc/userinfo``)
- 支持 OAuth2 Token 端点 (``/oidc/token``)
- JWT / JWE 加解密传输，使用 joserfc 库
- RSA 密钥自动生成与管理 (HMAC-SHA256 + RS256)

依赖更新
~~~~~~~~

- Authlib: OAuth 2.0 / OpenID Connect 协议实现
- joserfc: JWT / JWE 加密库
- Flask-PluginKit: 插件管理框架
- Peewee: ORM 数据库操作
- Click: CLI 命令行工具
