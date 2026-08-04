.. _quickstart:

快速上手
========

安装完成后，可通过以下步骤快速启动 passportd。

前置条件
--------

- 确认 Redis 服务已启动：``redis-cli ping``
- Python 3.10+

1. 初始化配置
-------------

passportd 启动时会自动检查配置，默认使用开发环境配置。你也可以通过命令行查看当前配置：

.. code-block:: shell

    passportd config

首次运行时会自动生成 RSA 密钥对（用于 OIDC JWT 签名）到 ``BASE_DIR/data/`` 目录。

2. 启动开发服务器
-----------------

.. code-block:: shell

    passportd run

默认监听 ``0.0.0.0:10030``，可通过环境变量修改：

.. code-block:: shell

    export PASSPORT_HOST=0.0.0.0
    export PASSPORT_PORT=5000
    passportd run

3. 启动生产服务器
------------------

.. code-block:: shell

    passportd start

使用 Gunicorn + gevent 作为生产环境 WSGI 服务器。

其他管理命令：

.. code-block:: shell

    passportd status     # 查看服务运行状态
    passportd stop       # 停止服务
    passportd restart    # 重启服务

4. 访问服务
-----------

- **前端页面（注册/登录/个人中心）**：http://localhost:10030/
- **OIDC 发现端点**：http://localhost:10030/.well-known/openid-configuration
- **API 接口**：http://localhost:10030/api/

5. 配置环境变量
---------------

passportd 支持通过 ``PASSPORT_`` 前缀的环境变量覆盖配置项。例如：

.. code-block:: shell

    export PASSPORT_DB_URI="mysql+pool://root:pwd@localhost:3306/passport?max_connections=20"
    export PASSPORT_REDIS_URI="redis://:pwd@localhost:6379/0"
    export PASSPORT_LOG_LEVEL="INFO"
    export PASSPORT_ENV="production"

也可以通过配置文件设置：

.. code-block:: shell

    export PASSPORT_CONFIG=/path/to/config.py

配置优先级（从低到高）：

1. ``BaseConfig`` 默认配置
2. ``DevConfig`` / ``ProdConfig`` 按环境选择
3. ``PASSPORT_CONFIG`` 指定的配置文件
4. ``PASSPORT_`` 前缀的环境变量

环境变量会自动映射，规则为去掉 ``PASSPORT_`` 前缀，转为大写。
例如 ``PASSPORT_DB_URI`` 对应配置项 ``DB_URI``。

6. 注册并登录
-------------

访问 http://localhost:10030/ 即可看到注册/登录页面。

你也可以通过 API 注册账号：

.. code-block:: shell

    curl -i "http://localhost:10030/api/user/signup" -d account=test -d password=123456 -d repassword=123456

7. 注册 OAuth2 客户端（OIDC Provider 模式）
--------------------------------------------

登录后，在个人中心创建 OIDC 客户端，或通过 API：

.. code-block:: shell

    # 先登录获取 sid
    curl -iL "http://localhost:10030/user/signin" -d account=test -d password=123456

    # 创建 OIDC 客户端
    curl -i -H "Authorization: sid $sid" \
      "http://localhost:10030/api/oidc/client" \
      -d name=myapp \
      -d scope=openid \
      -d redirect_uri=http://localhost:10030/callback
