更新日志
========

v2.8.1
------

新特性
~~~~~~

- 个人中心新增设置、修改用户名
- 新增 CLI 命令 ``create-superadmin`` 一键创建 superadmin 用户
- 新增隐私政策页面
- 支持 Geetest 行为验证码

变更
~~~~

- 登录/注册密码改为 RSA 加密传输（不支持 WebCrypto 时降级明文）
- 移除仅供测试使用的 ``POST /api/user/signup`` 注册接口
- 数据库建表时机由模块导入时改为应用启动时（``models.model.init_db()``）
- 安全审计日志移除分页，仅显示最新 10 条
- 插件管理页生产环境增加访问控制（uid 与 ``PLUGINKIT_AUTH_UID`` 一致才放行）
- 验证码登录即注册：账号不存在时自动创建无密码账号并登录，发送登录验证码不再要求账号已注册
- 移除邮箱/手机号注册（注册仅支持用户名 + 密码），删除 ``POST /api/send_signup_vcode`` 接口
- 登录页调整：Passkey 登录置于中间，「验证码登录」更名「验证码注册登录」，第三方登录按钮改为图标 + 名称横向展示

修复
~~~~

- 修复 Prometheus Gunicorn 指标在 Grafana 显示 no data 的问题
- 修复修改密码提示误导（新增 ``PASSWORD_SAME_AS_OLD`` 错误码）

v2.7.0
------

新特性
~~~~~~

- 新增站点配置（``SITE_TITLE``/``SITE_DESC``/``SITE_KEYWORDS``/``SITE_FAVICON``/``SITE_LOGO``）与 Prometheus 指标采集
- 新增 Grafana Dashboard 配置示例 ``examples/grafana_dashboard.json``
- 新增 CLI ``role`` 子命令组管理用户角色
- 登录安全：新增暴力破解防护（失败锁定 + IP 限流）
- 配置校验：``_check_config_value`` 启动校验范围扩展

变更
~~~~

- API 错误响应统一语言：后端英文 ``message`` + 错误码 ``code``，前端 ``ERROR_ZH`` 映射中文
- 前端创建/编辑 OIDC 客户端表单不再展示 ``role`` 授权范围选项
- OIDC 平台角色按客户端隔离输出（新增 ``OIDC_INTERNAL_CLIENTS`` 配置）
- 内置角色统一为小写存储
- 登录/注册按钮颜色反转
- 页脚 ICP 备案号配置项由 ``ICP`` 更名为 ``SITE_ICP``

v2.6.5
------

修复
~~~~

- 修复 Google OAuth2 回调 ``Failed to parse userinfo: 'sub'``（升级到 v3 端点）
- 修复 OAuth2 首次登录选择「直接创建账号」报 ``Invalid account or credential``
- 修复 CI 中 ``tests/test_login_security.py`` 依赖 pytest 导致 ``ModuleNotFoundError``（改用 unittest）

v2.6.4
------

修复
~~~~

- 修复登录页 ``{{ next }}`` 在 ``<script>`` 内被 autoescape 破坏的问题（改用 ``|tojson``）
- 修复 Passkey 登录成功后 ``sid`` Cookie 丢失的问题（改用 ``auto_set_user_state``）
- 修复 Google OAuth2 登录报 ``Missing "jwks_uri" in metadata``

v2.6.3
------

修复
~~~~

- 会话获取 IP 地点

变更
~~~~

- Flask-PluginKit 更新版本

v2.6.2
------

新特性
~~~~~~

- 活跃会话新增登录发起方记录（``UserSession.source`` 字段，自动识别 OIDC 登录来源）

.. code-block:: sql

   ALTER TABLE passport_user_session ADD COLUMN source VARCHAR(64) NOT NULL DEFAULT '';

- 安全中心活跃会话列表展示登录方式（``method``）和登录来源（``source``）

变更
~~~~

- 验证码登录 API 增加 ``next`` 参数传递

v2.6.1
------

新特性
~~~~~~

- 活跃会话新增登录方式记录（``UserSession.method`` 字段，区分 local/vcode/passkey/oauth2_github 等）

.. code-block:: sql

   ALTER TABLE passport_user_session ADD COLUMN method VARCHAR(32) NOT NULL DEFAULT '';

修复
~~~~

- 修复第三方 OAuth 登录（已绑定账号路径）未生成活跃会话的问题
- 修复活跃会话地理位置始终为空的问题
- 修复 daemon 线程无异常处理导致会话信息更新静默失败的问题

变更
~~~~

- ``changelog.rst`` 从 ``docs/`` 移至项目根目录并重命名为 ``CHANGELOG.rst``

v2.6.0
------

新特性
~~~~~~

- 新增安全审计日志功能（独立 ``AuditLog`` 模型 + 前端「安全」页面）
- 公告支持 ``closable`` 字段
- 新增活跃会话管理

变更
~~~~

- 「登录历史」从个人资料页移至安全页面
- IP 地理位置查询接口 ``IP_API_URL`` 改为可配置

v2.5.0
------

新特性
~~~~~~

- 新增账号注销功能
- 新增 Google OAuth2 登录支持

修复
~~~~

- 修复远程公告过滤失败的问题
- 修复邮箱账号无法解绑的问题
- 新增第三方社交账号解绑功能

v2.4.2
------

新特性
~~~~~~

- 新增公告通知功能

修复
~~~~

- 修复 Spug 短信发送时缺少 ``number`` 变量的问题

v2.4.1
------

修复
~~~~

- 修复 get_ip 函数

变更
~~~~

- 验证码登录新增「记住登录（7天有效）」选项

v2.4.0
------

新特性
~~~~~~

- WebAuthn Passkey 支持：注册并使用 Passkey 登录

修复
~~~~

- 修复登录页面宽度过窄（420px → 480px）

变更
~~~~

- SMTP 默认端口从 587 改为 465

v2.3.0
------

新特性
~~~~~~

- 「我的授权」管理页面
- 绑定 / 解绑邮箱和手机号
- 短信验证码日频限制
- 头像上传与裁剪（集成 Cropper.js）

修复
~~~~

- OIDC 授权页面显示客户端名称
- 多级代理环境获取真实 IP

变更
~~~~

- 「我的授权」独立页面取消，内容合并至 OIDC Client 页面下方
- 验证码登录 method 标记由 ``local_vcode`` 简化为 ``vcode``
- ``auto_create_data_dir()`` 改为接受路径参数
- 移除 Codecov 集成
- Dockerfile / kubernetes.yaml 统一使用 ``PASSPORT_BASE_DIR=/app``
- 解绑邮箱/手机号由验证码改为密码确认
- OIDC 客户端详情弹窗新增 Discovery 端点显示
- 个人资料头像改为上传 + 裁剪

v2.2.0
------

精简配置项

v2.1.0
------

Spug Push 验证码集成、登录方式扩展及多项修复优化。

新特性
~~~~~~

- 验证码注册登录：支持 SMTP / Spug Push 验证码模板发送邮件和短信
- 页脚新增 ICP 备案号显示

修复
~~~~

- 修复 GitHub Actions sdist 构建失败
- 修复 Sphinx 文档构建问题

变更
~~~~

- Redis key 统一 ``passportd:`` 前缀
- 修改密码功能更改

v2.0.0
------

重大更新，完全重构 OIDC 模块。

新特性
~~~~~~

- 基于 Authlib 重构 OIDC 模块，完整支持 OpenID Connect 协议
- OAuth2 插件化架构，基于 Flask-PluginKit 动态加载
- 内置 GitHub 和 Gitee OAuth2 登录支持
- 支持 Authorization Code Grant 授权流程
- 支持 OIDC Discovery / JWKS / UserInfo / Token 端点
- JWT / JWE 加解密传输，使用 joserfc 库
- RSA 密钥自动生成与管理

依赖更新
~~~~~~

- Authlib / joserfc / Flask-PluginKit / Peewee / Click
