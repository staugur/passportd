# passportd

认证、授权、统一登录 — 基于 Flask 的 SSO 单点登录服务。

[![PyPI](https://img.shields.io/pypi/v/passportd)](https://pypi.org/project/passportd/)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-passportd.readthedocs.io-brightgreen)](https://passportd.readthedocs.io/)

## 核心功能

- **本地账号系统**：支持用户名、手机号、邮箱注册与登录
- **WebAuthn Passkey**：支持指纹/面容/PIN 码免密登录，兼容 Windows Hello、Apple Touch ID、YubiKey、Vaultwarden 等
- **OAuth2 第三方登录**：内置 GitHub、Gitee、Weibo、QQ、Google等 OAuth2 登录插件
- **OpenID Connect Provider**：支持 OIDC Server 模式，可作为独立 SSO 服务
- **插件扩展**：基于 Flask-PluginKit 的插件架构，方便扩展更多登录方式
- **多数据库支持**：SQLite（开发） / MySQL / PostgreSQL（生产）
- **JWT 认证**：支持 HMAC-SHA256 和 RS256 双算法 JWT 签名
- **RESTful API**：提供完整的注册、登录、用户信息、OIDC 客户端管理接口

## 快速开始

### pip 安装

```shell
# 安装
pip install passportd

# 确保 Redis 已启动

# 开发模式启动
passportd run

# 生产模式启动
passportd start
```

访问 http://localhost:10030/ 即可看到登录页面。

### Docker 运行

```shell
# 拉取镜像
docker pull staugur/passportd:latest

# 启动容器（需要先启动 Redis）
docker run -d \
  --name passportd \
  -p 10030:10030 \
  -e PASSPORT_REDIS_URI="redis://:pwd@redis:6379/0" \
  -e PASSPORT_DB_URI="sqlite:///app/data/passportd.db" \
  -e PASSPORT_ENV="production" \
  -v passportd-data:/app/data \
  staugur/passportd:latest
```

也可以通过 `docker-compose.yml` 一键启动（包含 Redis）：

```yaml
version: "3.8"
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis-data:/data

  passportd:
    image: staugur/passportd:latest
    restart: unless-stopped
    ports:
      - "10030:10030"
    environment:
      - PASSPORT_ENV=production
      - PASSPORT_REDIS_URI=redis://redis:6379/0
      - PASSPORT_DB_URI=sqlite:///app/data/passportd.db
    volumes:
      - passportd-data:/app/data
    depends_on:
      - redis

volumes:
  redis-data:
  passportd-data:
```

## 文档

完整文档请访问 [passportd.readthedocs.io](https://passportd.readthedocs.io/)

本地构建文档：

```shell
pip install -r requirements/docs.txt
cd docs && make html
```

## 许可证

Apache License 2.0

## 备注

沿用 1.x 设计思路，使用 OIDC 标准协议重构实现，除核心代码外大部分使用 AI 生成。

如从 1.x 迁移，可使用 tools 脚本。
