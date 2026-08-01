# passportd 架构文档

## 1. 项目定位

passportd 是一个 **OpenID Connect (OIDC) / OAuth2 统一认证服务**，同时承担两个角色：

| 角色 | 说明 |
|---|---|
| **OAuth2 Client（消费者）** | 对接 GitHub / Gitee / QQ / 微博 等第三方 OAuth2 提供商，支持"第三方登录"和"账号绑定" |
| **OIDC Server（提供者）** | 自身作为 OIDC Provider，向注册的 OIDC Client 应用颁发授权码和 token，实现 SSO 单点登录 |

技术栈：Flask + Peewee ORM + authlib + Redis + JWT (joserfc)

---

## 2. 数据模型

### 2.1 表结构

```
┌──────────────────────────────────────────────────────────────────────┐
│  User  (passport_user)                用户资料 + 唯一密码              │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ uid (PK)    │ 22位唯一标识                                       │ │
│  │ nickname    │ 昵称                                               │ │
│  │ bio         │ 简介                                               │ │
│  │ gender      │ 0=女 1=男 2=未知                                    │ │
│  │ avatar      │ 头像 URL                                           │ │
│  │ location    │ 地区                                               │ │
│  │ password_hash│ 密码哈希 ★ (NULL=第三方用户无密码，所有本地方式共享)   │ │
│  │ role        │ 角色 (空格分隔): User Admin SuperAdmin ...          │ │
│  │ status      │ 0=禁用 1=启用                                       │ │
│  │ ctime/mtime │ 创建/修改时间戳                                     │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
         │ 1
         │
         │ N
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Auth  (passport_auth)                身份映射 (无 credential)         │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ uid         │ → User.uid                                         │ │
│  │ account (UK)│ 账号: "alice" / "github.12345" / "a@x.com"         │ │
│  │ classify    │ username / email / mobile / 3rd                     │ │
│  │ tpid        │ 第三方平台唯一 ID (仅第三方有效)                      │ │
│  │ ctime/mtime │ 创建/修改时间戳                                     │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  OAuthClient  (passport_oauth_client)  注册的 OIDC 客户端应用          │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ uid         │ 所属用户                                           │ │
│  │ name (UK)   │ 应用名称                                           │ │
│  │ client_id   │ 客户端 ID (24位随机串)                              │ │
│  │ client_secret│ 客户端密钥 (48位随机串)                            │ │
│  │ redirect_uri│ 回调地址                                           │ │
│  │ scope       │ openid profile ...                                 │ │
│  │ grant_type  │ authorization_code                                 │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  OAuthToken  (passport_oauth_token)    颁发的 access_token              │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ uid         │ 授权用户                                           │ │
│  │ client_id   │ 授权客户端                                         │ │
│  │ access_token│ Bearer token                                       │ │
│  │ expires_in  │ 过期秒数                                           │ │
│  │ scope       │ 授权范围                                           │ │
│  │ status      │ 1=有效 0=已撤销                                     │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  OAuthAuthorization  (passport_oauth_authorization) 授权记录           │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ uid         │ 授权用户 (谁点了"同意")                              │ │
│  │ client_id   │ 被授权应用                                         │ │
│  │ scope       │ 用户同意的权限范围                                   │ │
│  │ ctime       │ 授权时间                                           │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 关键设计原则

- **一个用户一份密码**：`password_hash` 存在 `User` 表，所有本地登录方式（username/email/mobile）共享同一密码
- **Auth 表不存 credential**：access_token 不入库，每次 OAuth 登录重新走授权流程
- **User.uid 唯一**：22 位随机字符串，是系统内用户的唯一标识

---

## 3. 本地账号注册与登录

### 3.1 注册流程

```
用户浏览器                          passportd
    │                                    │
    │  GET /user/signup                   │
    │ ──────────────────────────────────► │  渲染注册页 (signup.j2)
    │ ◄────────────────────────────────── │
    │                                    │
    │  POST /user/signup                  │
    │  { username, password, ... }        │
    │ ──────────────────────────────────► │
    │                                    │  add_profile(account, credential)
    │                                    │  ├─ parse_account_classify → "username"
    │                                    │  ├─ is_local_account? → True
    │                                    │  ├─ password_hash = generate_password_hash(credential)
    │                                    │  ├─ gen_uid() → 22位
    │                                    │  └─ DB事务:
    │                                    │     User(uid, nickname, ..., password_hash)
    │                                    │     Auth(uid, account, classify="username")
    │                                    │
    │                                    │  auto_set_user_state(account, expire, redirect)
    │                                    │  ├─ generate_jwt(account) → jwt
    │                                    │  └─ set_user_state(jwt, redirect_url, 7天)
    │                                    │     └─ Set-Cookie: sid=<jwt>; httponly; max-age=604800
    │ ◄──── 302 → / ├───────────────────── │
    │                                    │
```

### 3.2 登录流程

```
用户浏览器                          passportd
    │                                    │
    │  GET /user/signin                   │
    │ ──────────────────────────────────► │  渲染登录页 (signin.j2)
    │ ◄────────────────────────────────── │  含 OAuth2 第三方登录按钮
    │                                    │
    │  POST /user/signin                  │
    │  { username, password, remember }   │
    │ ──────────────────────────────────► │
    │                                    │  login(account, credential)
    │                                    │  ├─ has_account(account) → Auth 记录
    │                                    │  ├─ is_local_account → True
    │                                    │  ├─ User.get(uid=a.uid) → password_hash
    │                                    │  └─ check_password_hash(hash, credential)
    │                                    │     ├─ True → 生成 jwt
    │                                    │     └─ False → AuthError 返回登录页
    │                                    │
    │                                    │  auto_set_user_state(account, expire, redirect)
    │  ◄──── Set-Cookie: sid=<jwt> ────── │  302 → next_url 或首页
    │                                    │
```

### 3.3 登录态验证 (`parse_user_state`)

```
每个请求 before_request:
  ┌─ 优先级顺序:
  │  1. Cookie "sid" → request.cookies.get("sid")
  │  2. Authorization Header → "sid <jwt>"
  │  3. Query String → ?sid=<jwt>
  │
  │  verify_jwt(sid, dump=True)
  │  ├─ 先无签名解 payload 拿 uid + sub
  │  ├─ Auth.get(uid=uid, account=sub) 确认用户存在
  │  └─ jwt_decode(token, SECRET_KEY, sub) 验签
  │     ├─ 成功 → g.signin=True, g.user={uid, account}
  │     └─ 失败 → g.signin=False
  │
  │  装饰器保护:
  │  ┌─ login_required    → 页面路由，未登录 → 302 /user/signin?next=xxx
  │  ├─ anonymous_required → 已登录 → 302 /
  │  └─ apilogin_required → API路由，未登录 → 403 JSON
```

### 3.4 修改密码

```
POST /api/change_pwd
  { old_password, new_password, repassword }
  │
  change_password(uid, account, old_pwd, new_pwd)
  ├─ is_local_account → 只允许本地账号改密
  ├─ login(account, old_pwd) → 验证旧密码
  └─ User.password_hash = generate_password_hash(new_pwd)
     → 所有本地登录方式统一生效
```

---

## 4. 第三方 OAuth2 登录与绑定

### 4.1 作为 OAuth2 Client 的架构

```
┌─────────────────────────────────────────────────────────────────┐
│  PluginManager 加载 OAuth2 模块 (flask_pluginkit)                │
│                                                                 │
│  modules/oauth2_github/    → /oauth2/github/login               │
│  modules/oauth2_gitee/     → /oauth2/gitee/login                │
│  modules/oauth2_weibo/     → /oauth2/weibo/login                │
│  modules/oauth2_qq/        → /oauth2/qq/login                   │
│                                                                 │
│  每个模块提供两个路由:                                             │
│  ├─ /login     → 发起授权请求 (redirect 到第三方授权页)            │
│  └─ /authorize → 授权回调, 获取 token, 查询用户信息                │
│                                                                 │
│  回调结果由 libs/interface.py 处理:                               │
│  ├─ OAuthInterface (基类)                                        │
│  ├─ RegisterInterface  → 第三方首次登录 → 自动注册新用户            │
│  └─ LoginInterface     → 第三方登录                                │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 第三方首次登录（自动注册）

```
用户浏览器            passportd               GitHub
    │                     │                         │
    │  GET /user/signin   │                         │
    │ ◄──────────────────►│  渲染登录页              │
    │                     │                         │
    │  点击 "GitHub登录"   │                         │
    │ ───────────────────►│ /oauth2/github/login    │
    │ ◄──── 302 ──────────│ ──────────────────────► │ GET /authorize
    │                                          │
    │  GitHub 授权页                              │ 用户授权
    │ ◄────────────────────────────────────────► │
    │                                          │
    │ ◄───── 302 ──────────────────────────────│ code=xxx
    │ /oauth2/github/authorize?code=xxx         │
    │ ───────────────────►│                         │
    │                     │ token_endpoint → access_token
    │                     │ ──────────────────────► │
    │                     │ ◄──── access_token ──── │
    │                     │ userinfo_endpoint → 用户信息
    │                     │ ──────────────────────► │
    │                     │ ◄── {id, name, avatar} │
    │                     │
    │                     │ OAuthInterface.wrap(): account = "github.<id>"
    │                     │
    │                     │ RegisterInterface.check():
    │                     │ ┌─ has_account("github.<id>")
    │                     │ │  ├─ 不存在 → 新用户
    │                     │ │  └─ add_profile("github.<id>", access_token)
    │                     │ │     ├─ is_local_account → False
    │                     │ │     ├─ password_hash = None  (无密码)
    │                     │ │     └─ Auth(uid, account="github.<id>", classify="3rd", tpid="<id>")
    │                     │ │
    │                     │ │  auto_set_user_state → Set-Cookie: sid=<jwt>
    │                     │ └─ 302 → next_url
    │                     │
    │ ◄── 302 → next_url ─│
```

### 4.3 已注册用户绑定第三方账号

```
已登录用户在 Profile 页点击绑定 → /user/account?op=bind&provider=github
  │
  │  front.bind_oauth()
  │  ├─ 参数: op=bind, oauth_name=github
  │  ├─ 生成 oidc_state (JWT 保存绑定意图)
  │  ├─ 存 Redis: oidc_bind:<state_jwt> → {uid, oauth_name, action="bind"}
  │  └─ 302 → /oauth2/github/login?oidc_state=<state_jwt>
  │
  授权回调: /oauth2/github/authorize?state=<state_jwt>&code=xxx
  │
  │  OAuthInterface.wrap_userinfo(access_token)
  │  ├─ Redis 取 state → {uid, action="bind"}
  │  └─ account="github.<id>"
  │
  │  add_account(uid, "github.<id>", tpid="<id>")
  │  └─ Auth.create(uid, account, classify="3rd", tpid)
  │
  │  ← 302 → profile 页 "绑定成功"
```

**注意**：access_token 用完即弃，不入库。

---

## 5. 作为 OIDC Server 授权第三方应用

这是 passportd 的核心能力：**自身作为 OIDC Provider，向注册的 OIDC Client 签发身份令牌**。

### 5.1 授权码流程 (Authorization Code Flow)

```
  终端用户              OIDC Client App              passportd (OIDC Server)
    │                        │                              │
    │  访问第三方应用          │                              │
    │ ──────────────────────►│                              │
    │                        │                              │
    │                        │ GET /oauth/authorize         │
    │                        │  ?response_type=code         │
    │                        │  &client_id=<client_id>      │
    │                        │  &redirect_uri=<uri>         │
    │                        │  &scope=openid+profile        │
    │                        │  &state=<random>             │
    │   ◄── 302 ────────────│─────────────────────────────►│
    │                        │                              │
    │                        │   ① 验证 client_id 存在且有效
    │                        │   ② 检查 redirect_uri 匹配
    │                        │   ③ 检查用户登录态:
    │                        │      ├─未登录 → 302 /user/signin?next=<当前URL>
    │                        │      └─已登录 → 继续
    │                        │   ④ 检查是否已授权:
    │                        │      ├─新授权 → 渲染授权确认页 (authorize.j2)
    │                        │      └─已授权 → 跳过确认,直接生成 code
    │                        │
    │  用户点击 "授权"         │                              │
    │ ◄── 授权确认页 ────────│                              │
    │ ── confirm=yes ────────│─────────────────────────────►│
    │                        │                              │
    │                        │   ⑤ 生成 authorization_code
    │                        │   ⑥ save_oauth_authorization(uid, client_id, scope)
    │                        │   ⑦ 302 → redirect_uri?code=<code>&state=<state>
    │                        │                              │
    │                        │ ◄──── 302 ───────────────────│
    │                        │                              │
    │                        │ POST /oauth/token            │
    │                        │  grant_type=authorization_code│
    │                        │  &code=<code>                │
    │                        │  &client_id=<id>             │
    │                        │  &client_secret=<secret>     │
    │                        │ ────────────────────────────►│
    │                        │                              │
    │                        │   ⑧ 验证 code + client 凭据
    │                        │   ⑨ 生成 id_token (JWT) + access_token
    │                        │   ⑩ save_oauth_token(uid, client_id, token, ...)
    │                        │                              │
    │                        │ ◄── { access_token,           │
    │                        │       id_token,              │
    │                        │       token_type: "Bearer",  │
    │                        │       expires_in: 3600 }     │
    │                        │                              │
    │                        │ GET /oauth/userinfo          │
    │                        │  Authorization: Bearer <token>│
    │                        │ ────────────────────────────►│
    │                        │                              │
    │                        │   ⑪ 验 token → 返回用户 claims
    │                        │                              │
    │                        │ ◄── { sub, nickname,         │
    │                        │       avatar, ... }          │
    │                        │                              │
```

### 5.2 授权确认页 (authorize.j2)

用户首次授权某 OIDC Client 时会看到授权页：

```
┌──────────────────────────────────────────────┐
│  "示例应用" 请求访问你的账号                  │
│                                              │
│  该应用将获得以下权限:                         │
│  ☑ openid  - 获取你的用户标识                  │
│  ☑ profile - 获取你的基本资料 (昵称、头像等)    │
│                                              │
│  授权后该应用可在你未登录 passport 时使用你的身份 │
│                                              │
│  [ 拒绝 ]          [ 授权 ]                   │
└──────────────────────────────────────────────┘
```

- **拒绝**：浏览器重定向回 `redirect_uri?error=access_denied`
- **授权**：生成 code，重定向回 `redirect_uri?code=xxx&state=xxx`，记录授权到 `OAuthAuthorization` 表

### 5.3 OIDC Discovery

遵循 OpenID Connect Discovery 1.0 标准：

```
GET /.well-known/openid-configuration
→ {
    "issuer": "https://passport.example.com",
    "authorization_endpoint": "https://passport.example.com/oauth/authorize",
    "token_endpoint": "https://passport.example.com/oauth/token",
    "userinfo_endpoint": "https://passport.example.com/oauth/userinfo",
    "jwks_uri": "https://passport.example.com/oauth/jwks",
    "scopes_supported": ["openid", "profile"],
    "response_types_supported": ["code"],
    "grant_types_supported": ["authorization_code"],
    "id_token_signing_alg_values_supported": ["RS256"]
  }
```

### 5.4 ID Token 签发

```
id_token = JWT (RS256 签名)
  Header: { "alg": "RS256", "kid": "<key_id>" }
  Payload: {
    "iss": "https://passport.example.com",
    "sub": "<uid>",
    "aud": "<client_id>",
    "exp": <now + 3600>,
    "iat": <now>,
    "nickname": "...",
    "avatar": "...",
    ...
  }
```

### 5.5 OIDC Client 管理

用户可以在 profile 页面管理自己创建的 OIDC Client 应用：

```
GET  /oauth/client/list    → 列出我的所有 OIDC Client
POST /oauth/client/create  → 创建新 Client (name, redirect_uri, homepage, scope)
POST /oauth/client/update  → 更新 Client 信息
POST /oauth/client/delete  → 删除 Client (级联删除关联 Token)
GET  /oauth/client/count/<client_id> → 查看授权用户数
```

---

## 6. 核心路由一览

### 6.1 前端页面 (`views/front.py`)

| 路由 | 方法 | 功能 | 权限 |
|---|---|---|---|
| `/` | GET | 首页 | public |
| `/user/signup` | GET/POST | 注册页 | anonymous_required |
| `/user/signin` | GET/POST | 登录页 | anonymous_required |
| `/user/signout` | GET | 登出 (清除 sid cookie) | public |
| `/user/profile` | GET/POST | 个人资料编辑 | login_required |
| `/user/account` | GET | 账号管理 & OAuth 绑定 | login_required |

### 6.2 用户 API (`views/api.py`)

| 路由 | 方法 | 功能 | 权限 |
|---|---|---|---|
| `/api/user/me` | GET | 获取当前用户信息 | apilogin_required |
| `/api/user/<uid>` | GET | 获取指定用户资料 | apilogin_required |
| `/api/change_pwd` | POST | 修改密码 | apilogin_required |
| `/api/update_profile` | POST | 更新资料 | apilogin_required |
| `/api/client/create` | POST | 创建 OIDC Client | apilogin_required |
| `/api/client/update` | POST | 更新 OIDC Client | apilogin_required |
| `/api/client/delete` | POST | 删除 OIDC Client | apilogin_required |
| `/api/client/count/<client_id>` | GET | 查看授权数 | apilogin_required |
| `/api/client/list` | GET | 列出我的 Clients | apilogin_required |

### 6.3 OIDC Server (`views/oidc.py`)

| 路由 | 方法 | 功能 |
|---|---|---|
| `/.well-known/openid-configuration` | GET | OIDC Discovery |
| `/oauth/authorize` | GET/POST | 授权端点 (Authorization Code Flow) |
| `/oauth/token` | POST | Token 端点 (code→token) |
| `/oauth/userinfo` | GET | 用户信息端点 (Bearer token) |
| `/oauth/jwks` | GET | JWKS 公钥端点 (RS256验签) |

### 6.4 OAuth2 第三方登录

| 路由 | 方法 | 功能 |
|---|---|---|
| `/oauth2/github/login` | GET | 发起 GitHub 授权 |
| `/oauth2/github/authorize` | GET | GitHub 回调 |
| `/oauth2/gitee/login` | GET | 发起 Gitee 授权 |
| `/oauth2/gitee/authorize` | GET | Gitee 回调 |
| `/oauth2/weibo/login` | GET | 发起微博授权 |
| `/oauth2/weibo/authorize` | GET | 微博回调 |
| `/oauth2/qq/login` | GET | 发起 QQ 授权 |
| `/oauth2/qq/authorize` | GET | QQ 回调 |

---

## 7. 登录态传递机制

```
┌─────────────────────────────────────────────────────────────────┐
│  跨请求状态传递（系统要求无状态，禁用 Flask session）              │
│                                                                 │
│  JWT (sid)                                                      │
│  ├─ Cookie: sid=<jwt>; httponly; max-age=604800                │
│  ├─ Header:  Authorization: sid <jwt>                           │
│  └─ Query:   ?sid=<jwt>                                         │
│                                                                 │
│  OAuth 状态传递                                                   │
│  ├─ URL:  ?oidc_state=<jwt> (OAuth2 跳转携带)                   │
│  └─ Redis: oidc_bind:<state_jwt> → {uid, action, provider}     │
│            oidc_state:<state_jwt> → {next_url, ...}             │
│                                                                 │
│  安全校验                                                         │
│  ├─ is_safe_url(): 防止 open redirect (同 host + http/https)    │
│  └─ get_redirect_url(): next → default                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. 请求生命周期

```
请求进入
  │
  ▼
before_request (每个请求)
  ├─ db.connect(reuse_if_open=True)   ← 获取数据库连接（MySQL/PostgreSQL 使用连接池）
  └─ g.signin, g.user = parse_user_state()
     └─ Cookie → Header → Query 三级读取 sid JWT
        └─ verify_jwt → 验签 + 查 Auth 表确认用户存在
  │
  ▼
路由处理 (Blueprint)
  ├─ 装饰器检查: login_required / apilogin_required / anonymous_required
  ├─ 业务逻辑 (user.py / oidc.py / interface.py)
  └─ 返回 Response
  │
  ▼
after_request
  └─ CORS: Access-Control-Allow-Headers: Authorization
  │
  ▼
teardown_request
  └─ db.close()   ← 归还/关闭数据库连接
```

---

## 9. 项目结构

```
passportd/
├── app.py              ← Flask 应用工厂, create_app()
├── cli.py              ← CLI 命令 (run, start, stop, init, config)
├── basis/              ← 基础设施层
│   ├── conf.py         ← 配置加载
│   ├── errors.py       ← 异常类 (PassportError, ApiError, AuthError...)
│   ├── vars.py         ← 全局常量
│   └── common.py       ← 公共工具 (now, makedirs, new_res...)
├── models/             ← 数据模型 & 业务逻辑 ★
│   ├── model.py        ← Peewee ORM 表定义 (User, Auth, OAuthClient...)
│   ├── user.py         ← 用户 CRUD (add_profile, login, change_password...)
│   └── oidc.py         ← OIDC Client 管理 (create, update, delete...)
├── views/              ← 路由层 (Flask Blueprint)
│   ├── root.py         ← 蓝图注册
│   ├── front.py        ← 页面路由 (登录/注册/Profile/OAuth绑定)
│   ├── api.py          ← REST API
│   └── oidc.py         ← OIDC Server 端点 (authorize/token/userinfo/jwks)
├── libs/               ← 核心库 ★
│   ├── oidc.py         ← OIDC Server 实现 (authlib AuthorizationServer)
│   └── interface.py    ← OAuth2 Client 接口 (第三方登录/绑定)
├── utils/              ← 工具函数
│   ├── web.py          ← JWT, cookie, 登录态解析, OAuth2 提供商列表
│   └── common.py       ← 通用工具 (密码加密解析, 校验, 日志)
├── modules/            ← OAuth2 第三方插件
│   ├── oauth2_github/  ← GitHub OAuth2
│   ├── oauth2_gitee/   ← Gitee OAuth2
│   ├── oauth2_weibo/   ← Weibo OAuth2
│   └── oauth2_qq/      ← QQ OAuth2
└── templates/          ← Jinja2 模板
    ├── signin.j2       ← 登录页
    ├── signup.j2       ← 注册页
    ├── profile.j2      ← 个人资料
    ├── authorize.j2    ← OIDC 授权确认页
    └── error.j2        ← 错误页
```

---

## 10. 安全要点

| 机制 | 实现 |
|---|---|
| 密码存储 | `werkzeug.security.generate_password_hash` (pbkdf2:sha256) |
| 密码读取 | `check_password_hash`，从 `User.password_hash` 统一读取 |
| JWT 签名 | HMAC-SHA256 (内部 sid) + RS256 (ID Token) |
| API 错误 | `ApiError` 带正确 `status_code` (400/403)，AJAX error 回调处理 |
| 登出 | `Set-Cookie: sid=; expires=0` 清除 cookie |
| 密码泄露 | `list_users()` 和 `get_user_by_uid()` 排除 `password_hash` |
| 第三方 token | access_token 不入库，每次重新授权 |
| URL 安全 | `is_safe_url()` 防 open redirect |
