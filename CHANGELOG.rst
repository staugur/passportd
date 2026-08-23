更新日志
========

v2.8.4
------

新特性
~~~~~~

- 新增 Telegram Login Widget 第三方登录插件支持

修复
~~~~

- Telegram 登录回调兼容 GET 提交，浏览器直接访问回调地址不再返回 405
- 第三方账号修改密码提示本地化，不再误报“请输入密码”
- 第三方登录或未设置密码的账号注销时不再要求输入密码，凭登录态即可注销
- 第三方账号设置用户名（或绑定邮箱/手机号）后即可设置密码

变更
~~~~

- 新增全局代理配置，第三方模块专属代理为空时自动回退使用
- 安全审计日志仅返回最近 10 条，与登录记录保持一致

v2.8.3
------

新特性
~~~~~~

- 新增 微信、Apple、Xiaomi 插件支持
- 新增 Telegram Login Widget 第三方登录插件支持（未配置 Bot 用户名时自动通过 Bot API 获取，可配置代理访问 Telegram）

修复
~~~~

- 清理 OAuth 回调链路中无用的 ``access_token`` 参数
- MySQL/MariaDB 连接自动追加 ``charset=utf8mb4``
- 修复多进程部署下 Prometheus 进程/请求/耗时类指标 ``rate()`` 查询 no data 的问题

v2.8.2
------

修复
~~~~

- 修复数据库自动迁移偶发失败、无法自动补充新列的问题
- 用户自定义背景图读取改为 Redis 缓存，降低数据库压力
- 修复 Prometheus HTTP 请求指标在 Grafana 显示 no data 的问题
- 修复 Prometheus 进程 CPU 指标在 Grafana 显示 no data 的问题

v2.8.1
------

新特性
~~~~~~

- 个人中心新增设置、修改用户名
- 新增 CLI 命令 ``create-superadmin`` 一键创建 superadmin 用户
- 新增隐私政策页面
- 支持 Geetest 行为验证码
- 新增站点全局背景图配置，个人中心支持用户自定义背景图

.. code-block:: sql

   ALTER TABLE passport_user ADD COLUMN background_image VARCHAR(255) NOT NULL DEFAULT '';

变更
~~~~

- 登录/注册密码改为 RSA 加密传输（不支持 WebCrypto 时降级明文）
- 移除仅供测试使用的注册接口
- 数据库建表时机由模块导入时改为应用启动时
- 安全审计日志移除分页，仅显示最新 10 条
- 插件管理页生产环境增加访问控制
- 验证码登录即注册：未注册账号发送验证码即可自动创建并登录
- 注册仅支持用户名 + 密码，移除邮箱/手机号注册接口
- 登录页布局调整，第三方登录按钮样式优化

修复
~~~~

- 修复修改密码提示误导

v2.7.0
------

新特性
~~~~~~

- 新增站点信息配置（标题/描述/关键词/图标/logo）与 Prometheus 指标采集
- 新增 Grafana Dashboard 配置示例
- 新增 CLI ``role`` 子命令组管理用户角色
- 登录安全：新增暴力破解防护（失败锁定 + IP 限流）
- 配置校验：启动校验范围扩展

变更
~~~~

- API 错误响应统一语言：后端英文 ``message`` + 错误码 ``code``，前端映射中文
- 前端创建/编辑 OIDC 客户端表单不再展示 ``role`` 授权范围选项
- OIDC 平台角色按客户端隔离输出（新增 ``OIDC_INTERNAL_CLIENTS`` 配置）
- 内置角色统一为小写存储
- 登录/注册按钮颜色反转
- 页脚 ICP 备案号配置项更名（``ICP`` → ``SITE_ICP``）

v2.6.5
------

修复
~~~~

- 修复 Google OAuth2 回调解析用户信息失败的问题
- 修复 OAuth2 首次登录选择「直接创建账号」报错的问题
- 修复 CI 测试依赖 pytest 导致报错的问题（改用 unittest）

v2.6.4
------

修复
~~~~

- 修复登录页跳转参数被转义破坏的问题
- 修复 Passkey 登录成功后登录态 Cookie 丢失的问题
- 修复 Google OAuth2 登录元数据解析失败的问题

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

- 活跃会话新增登录发起方记录（自动识别 OIDC 登录来源）

.. code-block:: sql

   ALTER TABLE passport_user_session ADD COLUMN source VARCHAR(64) NOT NULL DEFAULT '';

- 安全中心活跃会话列表展示登录方式和登录来源

变更
~~~~

- 验证码登录支持跳转参数传递

v2.6.1
------

新特性
~~~~~~

- 活跃会话新增登录方式记录（区分本地/验证码/Passkey/第三方登录等）

.. code-block:: sql

   ALTER TABLE passport_user_session ADD COLUMN method VARCHAR(32) NOT NULL DEFAULT '';

修复
~~~~

- 修复第三方 OAuth 登录（已绑定账号路径）未生成活跃会话的问题
- 修复活跃会话地理位置始终为空的问题
- 修复活跃会话信息更新静默失败的问题

变更
~~~~

- ``changelog.rst`` 从 ``docs/`` 移至项目根目录并重命名为 ``CHANGELOG.rst``

v2.6.0
------

新特性
~~~~~~

- 新增安全审计日志功能
- 公告支持手动关闭
- 新增活跃会话管理

变更
~~~~

- 「登录历史」从个人资料页移至安全页面
- IP 地理位置查询接口改为可配置

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

- 修复 Spug 短信模板变量缺失导致发送失败的问题

v2.4.1
------

修复
~~~~

- 修复获取真实 IP 的问题

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

- 修复登录页面宽度过窄的问题

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
- 头像上传与裁剪

修复
~~~~

- OIDC 授权页面显示客户端名称
- 多级代理环境获取真实 IP

变更
~~~~

- 「我的授权」独立页面取消，内容合并至 OIDC Client 页面下方
- 验证码登录方式标记简化
- 数据目录自动创建改为接受路径参数
- 移除 Codecov 集成
- 容器部署统一使用 ``PASSPORT_BASE_DIR`` 配置数据目录
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

- Redis key 命名统一前缀
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
~~~~~~~~

- Authlib / joserfc / Flask-PluginKit / Peewee / Click
