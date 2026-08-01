更新日志
========

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
