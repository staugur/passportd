更新日志
========

v2.4.0
------

新特性
~~~~~~

- **WebAuthn Passkey 支持**：用户可注册并使用 Passkey（指纹/面容/PIN 码）进行登录，彻底替代密码。
  - 前端新增 Passkey 登录入口（登录页）和 Passkey 设备管理（个人主页），服务端未启用时前端自动隐藏。

修复
~~~~

- 修复登录页面宽度过窄（420px → 480px），避免「密码登录 / 验证码登录 / Passkey 登录」三个 Tab 文字被截断。
- 修复 Passkey 接口 ``_rp_id`` 为空的错误：业务方法改用 property 访问，确保 ``_ensure_config()`` 被调用。
- 修复 webauthn 3.0.0 中 ``RegistrationCredential`` / ``AuthenticationCredential`` 已移除 ``parse_obj()`` 的问题：直接传递 JSON dict。
- 改进 Passkey 设备名称识别：新增 AAGUID 映射表（支持 Bitwarden/Vaultwarden、1Password、Windows Hello、iCloud Keychain、YubiKey 等），无 UA 时精确显示具体设备名称。

v2.3.0
------

新特性
~~~~~~

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
~~~~~~

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
~~~~~~

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
