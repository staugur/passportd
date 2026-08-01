.. _install:

安装
====

passportd 需要 Python 3.10 或更高版本，依赖 Redis 服务。

使用 pip 安装
--------------

稳定版本
~~~~~~~~~

.. code-block:: shell

    pip install passportd

如果你需要 MySQL 数据库支持：

.. code-block:: shell

    pip install passportd[mysql]

如果你需要 PostgreSQL 数据库支持：

.. code-block:: shell

    pip install passportd[pgsql]

生产环境部署
~~~~~~~~~~~~~

安装生产环境依赖（包含 Gunicorn + gevent）：

.. code-block:: shell

    pip install passportd
    pip install gunicorn gevent setproctitle

使用 Docker 安装
-----------------

Docker Hub 拉取镜像
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: shell

    docker pull <your-username>/passportd:latest

Docker 运行（需要外部 Redis）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: shell

    docker run -d \
      --name passportd \
      -p 10030:10030 \
      -e PASSPORT_REDIS_URI="redis://:pwd@host.docker.internal:6379/0" \
      -e PASSPORT_DB_URI="sqlite:///app/data/passportd.db" \
      -e PASSPORT_ENV="production" \
      -v passportd-data:/app/data \
      <your-username>/passportd:latest

Docker Compose 一键启动（含 Redis）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

创建 ``docker-compose.yml``：

.. code-block:: yaml

    version: "3.8"
    services:
      redis:
        image: redis:7-alpine
        restart: unless-stopped
        volumes:
          - redis-data:/data

      passportd:
        image: <your-username>/passportd:latest
        restart: unless-stopped
        ports:
          - "10030:10030"
        environment:
          - PASSPORT_REDIS_URI=redis://redis:6379/0
          - PASSPORT_ENV=production
          - PASSPORT_DB_URI=sqlite:///app/data/passportd.db
        volumes:
          - passportd-data:/app/data
        depends_on:
          - redis

    volumes:
      redis-data:
      passportd-data:

启动服务：

.. code-block:: shell

    docker-compose up -d

Docker 环境变量说明
~~~~~~~~~~~~~~~~~~~

Docker 容器中通过 ``PASSPORT_`` 前缀环境变量进行配置，主要变量包括：

- ``PASSPORT_REDIS_URI``：Redis 连接地址（必需）
- ``PASSPORT_DB_URI``：数据库连接地址
- ``PASSPORT_ENV``：运行环境，设为 ``production`` 启用生产配置
- ``PASSPORT_HOST``：监听地址，默认 ``0.0.0.0``
- ``PASSPORT_PORT``：监听端口，默认 ``10030``
- ``PASSPORT_LOG_LEVEL``：日志级别，默认 ``INFO``

Docker 镜像默认启动 Gunicorn 生产服务器。如需开发模式，覆盖启动命令：

.. code-block:: shell

    docker run -p 10030:10030 <your-username>/passportd:latest run

.. note::

    Redis 是必需依赖。Docker 镜像本身不包含 Redis 服务，
    建议通过 docker-compose 同时启动 Redis 和 passportd。

从源码安装
-----------

.. code-block:: shell

    git clone https://github.com/staugur/passportd.git
    cd passportd
    pip install -e .

开发环境安装
-------------

.. code-block:: shell

    git clone https://github.com/staugur/passportd.git
    cd passportd
    pip install -e ".[dev]"

依赖说明
--------

passportd 主要依赖以下组件：

- **Flask**: Web 框架，提供路由、模板、请求处理等基础能力
- **Peewee**: ORM 数据库操作，支持 SQLite / MySQL / PostgreSQL 三种数据库
- **Redis**: 缓存和会话管理，用于存储临时令牌、验证码等
- **Authlib**: OAuth 2.0 / OpenID Connect 协议实现
- **joserfc**: JWT / JWE 加密与解密
- **Flask-PluginKit**: 插件管理框架，支持动态加载 OAuth2 登录插件
- **Click**: 命令行工具框架，提供 CLI 管理入口

.. note::

    数据库默认使用 SQLite，无需额外配置即可开发测试。生产环境建议使用 MySQL 或 PostgreSQL。

.. note::

    Redis 是必需依赖，用于存储验证码、临时令牌和跨请求状态数据。
    系统设计为无状态，所有跨请求上下文通过 Redis 传递。
