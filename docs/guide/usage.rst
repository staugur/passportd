.. _usage:

网站使用说明
============

本文档介绍 passportd 网站的核心功能使用方式，包括配置 GitHub OAuth2 第三方登录、创建 OIDC Client 提供 SSO 服务，以及管理 Passkey 设备。

配置 OAuth2 对接 GitHub
-----------------------

passportd 支持通过 GitHub OAuth2 App 实现第三方登录，用户点击 GitHub 按钮即可使用 GitHub 账号快速登录或绑定。

创建 GitHub OAuth App
^^^^^^^^^^^^^^^^^^^^^^

1. 登录 GitHub，进入 `Settings → Developer settings → OAuth Apps <https://github.com/settings/developers>`_，点击 **New OAuth App**。
2. 填写应用信息：

   - **Application name**：自定义（如 ``My Passport``），会显示在 GitHub 授权页面
   - **Homepage URL**：passportd 服务地址（如 ``https://passport.example.com``）
   - **Authorization callback URL**：``https://passport.example.com/oauth2/github/authorized``

3. 创建后记录 **Client ID**，并点击 **Generate a new client secret** 生成 **Client Secret**。

启用 GitHub 登录
^^^^^^^^^^^^^^^^^

在 passportd 中配置上述凭据，支持两种方式：

**方式一：环境变量（推荐）**

.. code-block:: shell

    export PASSPORT_GITHUB_CLIENT_ID="你的 Client ID"
    export PASSPORT_GITHUB_CLIENT_SECRET="你的 Client Secret"
    passportd restart

**方式二：直接编辑默认配置文件**

.. code-block:: python

    # passportd/basis/conf.py 或自定义配置文件
    GITHUB_CLIENT_ID = "你的 Client ID"
    GITHUB_CLIENT_SECRET = "你的 Client Secret"

配置生效后，登录页面会自动显示 GitHub 登录按钮。已登录用户也可在个人中心"绑定第三方登录"区域绑定 GitHub 账号。

配置 OAuth2 对接 Google
-----------------------

passportd 也支持通过 Google OAuth2 实现第三方登录。

创建 Google OAuth 2.0 凭据
^^^^^^^^^^^^^^^^^^^^^^^^^^^

1. 登录 `Google Cloud Console <https://console.cloud.google.com/>`_，选择一个项目或创建新项目。
2. 进入 `APIs & Services → Credentials <https://console.cloud.google.com/apis/credentials>`_，点击 **Create Credentials → OAuth client ID**。
3. 如果尚未配置 OAuth consent screen（同意屏幕），系统会引导完成：

   - **User Type**：选择 **External**（外部用户）
   - **App name**：自定义应用名称
   - **User support email**：你的邮箱
   - **Developer contact email**：你的邮箱
   - **Scopes** 和 **Test users**：暂时跳过，先点 SAVE AND CONTINUE

4. 创建 OAuth client ID：

   - **Application type**：选择 **Web application**
   - **Name**：自定义（如 ``Passportd``）
   - **Authorized redirect URIs**：点击 ADD URI，填写 ``https://passport.example.com/oauth2/google/authorized``
   - 点击 **Create**

5. 创建成功后，弹窗中会显示 **Client ID** 和 **Client Secret**，立即保存。

启用 Google 登录
^^^^^^^^^^^^^^^^^

.. code-block:: python

    # passportd/basis/conf.py 或自定义配置文件
    GOOGLE_CLIENT_ID = "你的 Client ID（类似 xxx.apps.googleusercontent.com）"
    GOOGLE_CLIENT_SECRET = "你的 Client Secret（类似 GOCSPX-xxxx）"

.. note::

    如果 OAuth consent screen 处于 **Testing** 模式，只有已添加的 Test users 可以登录。发布到生产环境前需要在
    `OAuth consent screen <https://console.cloud.google.com/apis/credentials/consent>`_ 中点击 **PUBLISH APP**。

.. note::

    passportd 还可配置 Gitee、QQ、Weibo、Google 等 OAuth2 第三方登录，配置方式与 GitHub 类似，
    对应配置项为 ``GITEE_CLIENT_ID`` / ``GITEE_CLIENT_SECRET`` 等，详见 :ref:`setup`。

创建 OIDC Client 提供认证服务
------------------------------

passportd 本身可作为一个 OpenID Connect Provider（身份提供者），为第三方应用提供基于 OIDC 协议的 SSO 单点登录服务。

创建客户端
^^^^^^^^^^

1. 登录 passportd，进入 **OIDC Client** 页面。
2. 点击「创建客户端」按钮，填写表单：

   - **客户端名称**：用于识别的名称，如 ``我的 Web 应用``
   - **重定向 URI**：OAuth 授权回调地址，如 ``https://myapp.example.com/oauth/callback``
   - **授权范围**：默认 ``openid``，还需 ``profile`` 可获取用户昵称、头像等信息
   - **描述**\ （可选）：应用用途说明

3. 提交成功后，系统会生成：

   - **Client ID**：应用唯一标识
   - **Client Secret**：用于服务端认证的密钥（请妥善保管）

.. tip::

    开发环境可填写多个 redirect URI，生产环境务必仅添加受信任的地址。

OAuth 授权流程
^^^^^^^^^^^^^^

passportd 支持标准 OAuth2 **Authorization Code** 授权码流程：

1. **跳转授权页**
   引导用户访问：

   ::

       https://passport.example.com/oauth2/authorize
         ?client_id=<Client ID>
         &redirect_uri=<回调地址>
         &response_type=code
         &scope=openid

2. **用户授权**
   用户在 passportd 页面上确认授权。

3. **获取 Token**
   回调地址收到 ``code`` 后，服务端用 Client Secret 换取 Token：

   .. code-block:: shell

        curl -v "https://passport.example.com/api/oauth2/token" \
          -d client_id=<Client ID> \
          -d client_secret=<Client Secret> \
          -d code=<回调 code> \
          -d grant_type=authorization_code

   返回 ``id_token``（JWT）和 ``access_token``。

4. **获取用户信息**
   使用 ``access_token`` 请求 UserInfo：

   .. code-block:: shell

        curl -v "https://passport.example.com/api/oidc/userinfo" \
          -H "Authorization: Bearer <access_token>"

   返回当前登录用户的昵称、头像等基本信息。

OIDC 高级功能
^^^^^^^^^^^^^^

passportd 实现了 OpenID Connect 标准端点，可用于 OIDC Discovery：

- **Discovery 端点**：``/.well-known/openid-configuration``
- **JWKS 端点**\ （JWT 签名公钥）：``/api/oidc/certs``
- **UserInfo 端点**：``/api/oidc/userinfo``

在 OIDC Client 页面还可管理已创建的客户端（查看密钥、编辑信息、删除），以及查看已授权的应用列表。

管理 Passkey 设备
------------------

Passkey 是一种基于 WebAuthn 标准的无密码认证方式，支持指纹、面部识别、PIN 码等生物特征认证。passportd 支持 Passkey 登录和设备管理。

前提条件
^^^^^^^^

- 浏览器支持 WebAuthn API（Safari 17+、Chrome 67+、Firefox 60+ 均支持）
- 使用 HTTPS 或 localhost（生产环境必须 HTTPS）

绑定 Passkey
^^^^^^^^^^^^^

1. 登录 passportd，进入「个人主页」。
2. 向下滚动到 **Passkey 管理** 区域。
3. 点击「绑定 Passkey」按钮。
4. 浏览器弹出系统认证对话框，使用 Touch ID / Windows Hello / 安全密钥完成认证。
5. 绑定成功后，设备信息会自动记录，名称默认根据系统环境自动解析（如 ``Platform Passkey``）。

设备列表
^^^^^^^^

Passkey 管理区域会列出所有已绑定的设备，包含：

- **设备名称**：自动识别或手动修改的名称
- **绑定时间**：首次绑定的时间
- **最近使用**：最后一次使用 Passkey 登录的时间

重命名设备
^^^^^^^^^^

点击设备行右侧的「重命名」按钮，设备名称变为输入框：

- **Enter** 或失焦：保存新名称
- **Escape**：取消编辑
- 名称最多 128 字符

删除设备
^^^^^^^^

点击「删除」按钮并确认后，该 Passkey 设备将从账户中移除，不再可用于登录。

.. warning::

    删除 Passkey 设备后，该设备将 **立即** 无法用于登录。请确保至少保留一个可用的 Passkey 设备，
    或同时绑定了其他登录方式（密码、第三方账号），避免无法登录。

使用 Passkey 登录
^^^^^^^^^^^^^^^^^^

1. 进入登录页面，切换到「Passkey 登录」选项卡。
2. 点击「使用 Passkey 登录」按钮。
3. 系统弹出认证对话框，完成生物认证后即自动登录。

如果你的设备已绑定多个 Passkey，系统会列出供你选择。

重复绑定保护
^^^^^^^^^^^^^

如果尝试在同一个设备上重复绑定 Passkey，系统会显示提示「此设备已绑定 Passkey，无需重复绑定」，避免重复添加相同的设备凭据。

命令行工具
---------------------

passportd 提供一套命令行管理工具，用于启动/停止服务、查看配置、创建超级管理员与用户角色管理等。执行 ``passportd --help`` 可查看全部子命令，每个子命令支持 ``-h``/``--help`` 查看详细参数。

服务管理
^^^^^^^^^

.. code-block:: shell

    passportd run        # 启动 Flask 内置开发服务器（本地调试）
    passportd start      # 启动生产服务器（Gunicorn + gevent）
    passportd status     # 查看服务运行状态（运行中 / 未运行 / 残留 pid）
    passportd stop       # 优雅停止服务（SIGTERM，超时后强制结束）
    passportd restart    # 重启服务（先停止再启动）
    passportd config     # 打印当前完整配置（JSON 格式）

创建超级管理员
^^^^^^^^^^^^^^^

系统初始化时可通过 ``create-superadmin`` 命令创建第一个超级管理员（角色为 ``superadmin``），**仅支持 username 格式账号**，相当于注册一个用户名账号并赋予超级管理员角色：

.. code-block:: shell

    passportd create-superadmin rootadmin

命令会交互式提示输入密码（隐藏输入并二次确认），也可以直接指定：

.. code-block:: shell

    passportd create-superadmin rootadmin \
        --password "Root@123456" \
        --nickname "超级管理员"

- 账号必须是合法用户名：小写字母开头，3-32 位小写字母/数字/下划线
- 密码 6-32 位
- 创建成功后自动写入 ``role_set`` 审计日志
- 该命令仅用于**创建**新用户，不修改现有用户；如需调整现有用户角色请使用 ``role`` 子命令

角色管理
^^^^^^^^^

通过 ``role`` 子命令组管理已有用户的角色。内置角色统一小写存储（``admin`` / ``superadmin`` / ``user``），客户端角色使用 ``ClientName:Role`` 格式（原样保留）。

.. code-block:: shell

    passportd role list                  # 列出所有管理员（admin + superadmin）
    passportd role list --role admin     # 仅列出 admin 角色用户
    passportd role set <uid> superadmin  # 将用户角色替换为 superadmin
    passportd role add <uid> admin       # 向用户追加 admin 角色
    passportd role remove <uid> admin    # 从用户移除 admin 角色

- 多个角色用空格分隔，如 ``passportd role set <uid> superadmin admin``
- ``add`` 自动去重，``remove`` 仅移除已存在的角色
- 每次角色变更都会写入审计日志
