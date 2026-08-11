.. passportd documentation master file

=========
passportd
=========

认证、授权、统一登录。passportd 是一个基于 Flask 的 SSO（单点登录）服务，
提供 OAuth2 第三方登录和 OpenID Connect 协议支持。

核心功能
--------

- **本地账号系统**：支持用户名、手机号、邮箱注册与登录，支持Passkey通行密钥登录。
- **OAuth2 第三方登录**：内置 GitHub、Gitee、Weibo、QQ、Google OAuth2 登录插件
- **OpenID Connect Provider**：可作为独立 SSO 服务，支持 Discovery、JWKS、UserInfo 等标准端点
- **插件扩展**：基于 Flask-PluginKit 的插件架构，方便扩展更多登录方式
- **多数据库支持**：SQLite（开发）/ MySQL / PostgreSQL（生产）
- **JWT 认证**：支持 HMAC-SHA256 和 RS256 双算法签名
- **RESTful API**：提供完整的用户管理与 OIDC 客户端管理接口
- **无状态设计**：不依赖 Flask Session，跨请求状态通过 Redis + JWT + Cookie 传递

架构概览
--------

passportd 采用分层架构：

.. code-block:: text

    passportd/
    ├── app.py            # Flask 应用工厂 (create_app)
    ├── cli.py            # CLI 命令行管理工具
    ├── basis/            # 基础设施层（配置、异常、Mixins）
    ├── utils/            # 工具层（JWT、Redis、URL、验证）
    ├── models/           # 数据访问层（Peewee ORM）
    ├── libs/             # 业务逻辑层（注册、登录、OIDC）
    ├── views/            # 视图层（API、前端页面、OIDC 协议）
    └── modules/          # 可插拔 OAuth2 模块（GitHub、Gitee、Google）

用户指南
--------

.. toctree::
    :maxdepth: 2

    guide/index

API 参考
--------

.. toctree::
    :maxdepth: 2

    api/index

附录
----

.. toctree::
    :maxdepth: 2

    changelog
