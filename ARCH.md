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
│  LoginRecord  (passport_login_record)    登录历史                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ uid         │ 用户 uid                                           │ │
│  │ account     │ 登录账号                                           │ │
│  │ method      │ 登录方式: local / oauth2_xxx / passkey              │ │
│  │ ip          │ 客户端 IP                                          │ │
│  │ location    │ 地理位置 (城市/省份/国家)                            │ │
│  │ user_agent  │ 原始 User-Agent                                    │ │
│  │ browser     │ 解析后的浏览器名                                    │ │
│  │ os          │ 解析后的操作系统                                    │ │
│  │ device      │ 设备类型: Desktop / Mobile / Tablet                 │ │
│  │ fingerprint │ 浏览器指纹哈希                                      │ │
│  │ ctime       │ 登录时间戳                                         │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  PasskeyCredential  (passport_passkey_credential)  Passkey 凭证        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ credential_id│ 凭证 ID (Base64URL, PK)                           │ │
│  │ uid          │ → User.uid                                        │ │
│  │ public_key   │ 公钥 (DER 格式)                                   │ │
│  │ sign_count   │ 签名次数 (防重放)                                  │ │
│  │ device_name  │ 设备名称 (AAGUID 识别)                             │ │
│  │ credential_type│ 凭证类型: platform / cross-platform              │ │
│  │ status       │ 1=启用 0=已撤销                                    │ │
│  │ ctime        │ 绑定时间                                           │ │
│  │ ltime        │ 最后使用时间                                       │ │
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

passportd 支持三种注册方式，均自动创建用户并登录：

| 方式 | 账号类型 | 是否需要验证码 |
|------|----------|----------------|
| 用户名 | username | 否 |
| 邮箱 | email | 是（6 位数字验证码） |
| 手机号 | mobile | 是（6 位数字验证码） |

#### 3.1.1 用户名注册

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

#### 3.1.2 邮箱/手机号注册（验证码）

```
用户浏览器                          passportd                      邮箱/SMS
    │                                    │                            │
    │  GET /user/signup                   │                            │
    │ ◄────────────────────────────────── │                            │
    │                                    │                            │
    │  点击 "发送验证码"                   │                            │
    │  POST /api/send_signup_vcode        │                            │
    │  { account: "a@x.com" }            │                            │
    │ ──────────────────────────────────► │                            │
    │                                    │  60s 内同账号防重复发送       │
    │                                    │  generate_digital_verification_code()
    │                                    │  → 6位数字                   │
    │                                    │  Redis: signup_vcode:<account>
    │                                    │  ├─ 存 code                  │
    │                                    │  └─ expire = 300s (5分钟)    │
    │                                    │ ────────────────────────────►│ 发送邮件/SMS
    │ ◄──── { ok: true } ──────────────── │                            │
    │                                    │                            │
    │  POST /user/signup                  │                            │
    │  { account, password, vcode }       │                            │
    │ ──────────────────────────────────► │                            │
    │                                    │  校验验证码:
    │                                    │  ├─ Redis 取 signup_vcode:<account>
    │                                    │  └─ 比对 → 一致则继续
    │                                    │  add_profile(account, password)
    │                                    │  Redis 删除验证码              │
    │                                    │  auto_set_user_state(...)     │
    │ ◄──── 302 → / ├───────────────────── │                            │
```

### 3.2 登录流程

登录页提供两个 Tab：**密码登录**和**验证码登录**。忘记密码已取消独立重置流程，引导用户使用验证码登录后直接修改密码。

#### 3.2.1 密码登录

```
用户浏览器                          passportd
    │                                    │
    │  GET /user/signin                   │
    │ ──────────────────────────────────► │  渲染登录页 (signin.j2)
    │ ◄────────────────────────────────── │  含 OAuth2 第三方登录按钮
    │                                    │
    │  POST /user/signin                  │
    │  { account, password, remember }    │
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

#### 3.2.2 验证码登录

```
用户浏览器                          passportd                      邮箱/SMS
    │                                    │                            │
    │  切换到"验证码登录"Tab               │                            │
    │  输入邮箱/手机号，点击"发送验证码"     │                            │
    │  POST /api/vcode                    │                            │
    │  { account: "a@x.com" }            │                            │
    │ ──────────────────────────────────► │                            │
    │                                    │  VCodeInterface().send(account)
    │                                    │  ├─ generate_digital_verification_code()
    │                                    │  ├─ Redis: vcode:<account> (300s 有效)
    │                                    │  └─ 60s 防重复发送           │
    │                                    │ ────────────────────────────►│ 发送邮件/SMS
    │ ◄──── { ok: true } ──────────────── │                            │
    │                                    │                            │
    │  POST /api/vcode_login              │                            │
    │  { account, vcode, remember }       │                            │
    │ ──────────────────────────────────► │                            │
    │                                    │  校验验证码:
    │                                    │  ├─ Redis 取 vcode:<account>
    │                                    │  └─ 比对 → has_account(account)
    │                                    │  RecordLoginInterface() 记录登录日志
    │                                    │  auto_set_user_state(...)
    │ ◄──── Set-Cookie: sid=<jwt> ──────── │                            │
    │                                    │                            │
    │  忘记密码? 点击后自动切到此 Tab        │                            │
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

修改密码仅在已登录状态下允许（`@apilogin_required`），因此不需要验证旧密码。
仅需确认新旧密码不相同即可。

```
POST /api/change_pwd
  { new_password, repassword }
  │
  change_password(uid, account, new_pwd)
  ├─ is_local_account → 只允许本地账号改密
  ├─ check_password_hash(hash, new_pwd) → 新旧密码相同则拒绝
  └─ User.password_hash = generate_password_hash(new_pwd)
     → 所有本地登录方式统一生效
```

> 忘记密码的用户可通过验证码登录后直接修改密码，无需独立的"重置密码"流程。

### 3.5 验证码机制

passportd 统一使用 `generate_digital_verification_code()` 生成 **6 位数字验证码**，适用于注册和登录场景。

| 场景 | Redis Key | 有效期 | 防重复 | 发送接口 |
|------|-----------|--------|--------|----------|
| 登录验证码 | `vcode:<account>` | 300s (5分钟) | 60s | `VCodeInterface.send()` |
| 注册验证码 | `signup_vcode:<account>` | 300s (5分钟) | 60s | `VCodeInterface.send()` |

**验证码生成与校验流程：**

```
generate_digital_verification_code()
  └─ 从 "0123456789" 随机选取 6 位数字
     └─ 支持 1-10 位长度（默认 6）
```

**发送渠道**（通过 `VCodeInterface`）：

| 账号类型 | 发送方式 | 配置 |
|----------|----------|------|
| email | SMTP 邮件（465+SSL） | `SMTP_*` 配置项 |
| mobile | 短信（Spug API） | `SPUG_*` 配置项 |

```
POST /api/vcode 或 POST /api/send_signup_vcode
  { account: "a@x.com" 或 "13800138000" }
  │
  VCodeInterface().send(account)
  ├─ parse_account_classify(account) → email / mobile
  ├─ 60s 内同账号已发送 → 拒绝（防刷）
  ├─ generate_digital_verification_code() → 6 位 code
  ├─ Redis SETEX: vcode:<account> = code, TTL=300
  └─ 发送邮件/SMS
```

### 3.6 登录历史

每次登录（密码、验证码、OAuth2 第三方）都会通过 `RecordLoginInterface` 写入登录历史。

```
RecordLoginInterface(uid, account, method, request, fingerprint)
  │
  ├─ get_real_ip(request)        → 提取客户端 IP
  ├─ IPQueryInterface(ip)        → 地理位置 (省份/城市/国家)
  ├─ parse_user_agent(ua)        → { browser, os, device }
  └─ LoginRecord.create(...)     → 写入 passport_login_record 表
```

查询接口：
```
GET /api/login_history
  → { login_history: [...] }
```

### 3.7 Passkey 登录、绑定与管理

Passkey 基于 **WebAuthn** 标准，使用设备的生物识别（指纹/面容）或 PIN 码完成免密登录。

**前置条件**：配置 ``PASSKEY_RP_ID`` 为有效域名（开发环境默认 ``localhost``）。

#### 3.7.1 登录流程

```
用户点击「Passkey 登录」
  │
  POST /api/passkey/login/options (无需登录态)
  ├─ PasskeyClient.generate_authentication_options()
  │   ├─ rp_id   ← get_rp_id()   (从 PASSKEY_RP_ID 或请求 Host 推导)
  │   ├─ origin  ← get_origin()   (从 request.host_url 推导)
  │   └─ save_passkey_challenge("login:__anonymous__", challenge)
  └─ 返回 { challenge, rpId, allowCredentials }
      │
      ▼ 浏览器调用
  navigator.credentials.get({ publicKey: options })
      │
      ▼ 返回 credential
  POST /api/passkey/login/verify
  ├─ PasskeyClient.verify_authentication_response(credential_json, uid=None)
  │   ├─ get_passkey_challenge("login:__anonymous__") → 读取并清除 challenge
  │   ├─ PasskeyCredential.get(credential_id=...) → 查找凭证
  │   ├─ verify_authentication_response(credential=credential_json, ...)
  │   │   └─ 验证签名 + challenge + rp_id + origin
  │   └─ 更新 sign_count 和 ltime
  ├─ 签发 JWT (sid cookie)
  ├─ RecordLoginInterface(method="passkey", ...) → 记录登录
  └─ 返回 success + token
```

#### 3.7.2 凭证绑定流程

```
用户已登录 → 个人中心 → 点击「绑定 Passkey」
  │
  POST /api/passkey/register/options (@apilogin_required)
  ├─ PasskeyClient.generate_registration_options(uid, username)
  │   ├─ rp_id, rp_name ← 配置
  │   ├─ user_id, user_name, user_display_name
  │   ├─ save_passkey_challenge(uid, challenge)
  │   └─ 返回 { challenge, rp, user }
      │
      ▼ 浏览器调用
  navigator.credentials.create({ publicKey: options })
      │
      ▼ 返回 credential
  POST /api/passkey/register/verify (@apilogin_required)
  ├─ PasskeyClient.verify_registration_response(credential_json, uid)
  │   ├─ get_passkey_challenge(uid) → 读取并清除 challenge
  │   ├─ verify_registration_response(credential=credential_json, ...)
  │   │   └─ 验证签名 + challenge + rp_id + origin
  │   ├─ _parse_device_name(clientDataJSON, credential_json, verification)
  │   │   ├─ 1. userAgent → "Chrome on Windows"
  │   │   ├─ 2. AAGUID  → "Bitwarden / Vaultwarden" / "YubiKey 5"
  │   │   └─ 3. credential_device_type → "Cross-Platform Multi Device"
  │   ├─ PasskeyCredential.create(credential_id, uid, public_key, ...)
  │   └─ 返回 { credential_id, device_name }
  └─ 返回 success + 设备名称
```

#### 3.7.3 设备名称识别

```
_parse_device_name(clientDataJSON, credential_json, verification)
  │
  ├─ 1. 解析 userAgent（浏览器场景）
  │      "Mozilla/5.0 ... Chrome/120 ... Windows NT 10.0 ..."
  │      → "Chrome on Windows"
  │
  ├─ 2. AAGUID 精确匹配（密码管理器 / 硬件密钥）
  │      内置映射表 _AAGUID_MAP:
  │        b93fd961-... → "Bitwarden / Vaultwarden"
  │        ea9b8d66-... → "iCloud Keychain"
  │        fa2b99c1-... → "YubiKey 5 (FIDO2)"
  │        ...
  │
  └─ 3. 降级描述（未知 AAGUID）
         authenticatorAttachment + credential_device_type
         → "Cross-Platform Multi Device Synced Authenticator"
```

#### 3.7.4 凭证管理

```
GET  /api/passkey/credentials        → 列出当前用户所有绑定的凭证
DELETE /api/passkey/credential/<id>  → 删除指定凭证（软删除，status=0）
```

#### 3.7.5 安全机制

| 机制 | 实现 |
|------|------|
| Challenge 一次性 | 每次注册/登录后立即从 Redis 清除，防重放 |
| origin 校验 | ``verify_*_response`` 校验 origin 防止跨站攻击 |
| rp_id 校验 | 校验 rp_id 与当前服务匹配 |
| sign_count | 每次认证递增，检测签名计数器回退 |
| credential_backed_up | 多设备同步凭证标记为 Synced |

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
│  ├─ LoginInterface     → 第三方登录                                │
│  ├─ VCodeInterface     → 发送验证码 (邮件/SMS), 防重复             │
│  └─ RecordLoginInterface → 记录登录历史到 LoginRecord 表          │
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
    │ /oauth2/github/authorized?code=xxx         │
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
  授权回调: /oauth2/github/authorized?state=<state_jwt>&code=xxx
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
| `/user/signup` | GET/POST | 注册页（用户名/邮箱/手机号） | anonymous_required |
| `/user/signin` | GET/POST | 登录页（密码 & 验证码双 Tab） | anonymous_required |
| `/user/signout` | GET | 登出 (清除 sid cookie) | public |
| `/user/profile` | GET/POST | 个人资料编辑 & 修改密码 | login_required |
| `/user/account` | GET | 账号管理 & OAuth 绑定 | login_required |
| `/ping` | GET | Kubernetes 健康检查探针 | public |

### 6.2 用户 API (`views/api.py`)

| 路由 | 方法 | 功能 | 权限 |
|---|---|---|---|
| `/api/key` | POST | 获取 RSA 公钥（前端加密用） | public |
| `/api/user/me` | GET | 获取当前用户信息 | apilogin_required |
| `/api/user/<uid>` | GET | 获取指定用户资料 | apilogin_required |
| `/api/signup` | POST | 注册新用户 | anonymous_required |
| `/api/change_pwd` | POST | 修改密码 | apilogin_required |
| `/api/update_profile` | POST | 更新资料 | apilogin_required |
| `/api/vcode` | POST | 发送登录验证码（邮箱/SMS） | public (60s 防重复) |
| `/api/vcode_login` | POST | 验证码登录 | public |
| `/api/send_signup_vcode` | POST | 发送注册验证码（邮箱/SMS） | public (60s 防重复) |
| `/api/login_history` | GET | 登录历史记录 | apilogin_required |
| `/api/upload` | POST | 上传头像/文件 | apilogin_required |
| `/api/client/create` | POST | 创建 OIDC Client | apilogin_required |
| `/api/client/update` | POST | 更新 OIDC Client | apilogin_required |
| `/api/client/delete` | POST | 删除 OIDC Client | apilogin_required |
| `/api/client/count/<client_id>` | GET | 查看授权数 | apilogin_required |
| `/api/client/list` | GET | 列出我的 Clients | apilogin_required |

**Passkey API：**

| 路由 | 方法 | 功能 | 权限 |
|---|---|---|---|
| `/api/passkey/login/options` | POST | 生成登录认证选项 | public (需 PASSKEY_RP_ID 有效) |
| `/api/passkey/login/verify` | POST | 验证登录签名并签发 JWT | public |
| `/api/passkey/register/options` | POST | 生成注册选项 | apilogin_required |
| `/api/passkey/register/verify` | POST | 验证注册结果并存储凭证 | apilogin_required |
| `/api/passkey/credentials` | GET | 列出用户所有凭证 | apilogin_required |
| `/api/passkey/credential/<id>` | DELETE | 删除指定凭证 | apilogin_required |

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
| `/oauth2/github/authorized` | GET | GitHub 回调 |
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
├── version.py          ← 版本号
├── basis/              ← 基础设施层
│   ├── conf.py         ← 配置加载 (Dev/Prod + PinConfig 固定值)
│   ├── errors.py       ← 异常类 (PassportError, ApiError, AuthError...)
│   ├── vars.py         ← 全局常量
│   ├── common.py       ← 公共工具 (new_res, is_true, now, raise_version...)
│   └── mixin.py        ← Mixin 类 (SMTP, Upload, IPQuery, Spug...)
├── models/             ← 数据模型 & 业务逻辑 ★
│   ├── model.py        ← Peewee ORM 表定义 (User, Auth, OAuthClient, LoginRecord, PasskeyCredential...)
│   ├── user.py         ← 用户 CRUD (add_profile, login, change_password, record_login...)
│   └── oidc.py         ← OIDC Client 管理 + Token/Authorization 操作
├── views/              ← 路由层 (Flask Blueprint)
│   ├── root.py         ← 蓝图注册
│   ├── front.py        ← 页面路由 (登录/注册/Profile/OAuth绑定)
│   ├── api.py          ← REST API (用户、验证码、OIDC Client、上传、登录历史、Passkey)
│   └── oidc.py         ← OIDC Server 端点 (authorize/token/userinfo/jwks)
├── libs/               ← 核心库 ★
│   ├── oidc.py         ← OIDC Server 实现 (authlib AuthorizationServer)
│   └── interface.py    ← 业务接口层 (OAuth/Register/Login/VCode/Upload/RecordLogin/Passkey)
├── utils/              ← 工具函数
│   ├── web.py          ← JWT签发验证, Cookie, 登录态解析, OAuth2提供商列表, get_origin/get_rp_id
│   └── common.py       ← 通用工具 (校验、RSA密钥、JWE加解密、验证码生成、UA解析、Passkey challenge 缓存)
├── modules/            ← OAuth2 第三方插件
│   ├── oauth2_github/  ← GitHub OAuth2 (__state__ 自动检测启用/禁用)
│   ├── oauth2_gitee/   ← Gitee OAuth2
│   ├── oauth2_weibo/   ← 微博 OAuth2
│   └── oauth2_qq/      ← QQ OAuth2
├── templates/          ← Jinja2 模板
│   ├── signin.j2       ← 登录页（密码 & 验证码 & Passkey 三 Tab）
│   ├── signup.j2       ← 注册页（用户名 & 邮箱/手机号双 Tab）
│   ├── profile.j2      ← 个人资料 & 修改密码 & Passkey 管理
│   ├── authorize.j2    ← OIDC 授权确认页
│   ├── layout.j2       ← 基础布局 (含 Passkey 开关全局变量)
│   └── error.j2        ← 错误页
├── static/             ← 前端静态资源 (Bulma, FontAwesome, jQuery, favicon)
└── data/               ← 运行时数据 (SQLite, RSA密钥)
```
```
项目根目录/
├── Makefile            ← 构建工具 (clean/lint/dev/test/docs)
├── codecov.yml         ← Codecov 覆盖率配置
├── Dockerfile          ← Docker 镜像
├── kubernetes.yaml     ← K8s 部署配置
├── requirements/       ← pip 依赖 (base/dev/prod/docs)
├── tests/              ← 测试套件
│   ├── test_api.py             ← API 接口测试 (key/signup/change_password/login_history/upload)
│   ├── test_passkey.py         ← Passkey 接口测试 (注册/认证/凭证管理)
│   ├── test_util_common.py     ← utils/common.py 工具函数测试
│   ├── test_basis_common.py    ← basis/common.py 基础函数测试
│   └── test_basis_errors.py    ← basis/errors.py 异常体系测试
├── .github/workflows/  ← CI/CD
│   ├── ci.yml          ← 自动化测试 + Codecov 上传 (Python 3.10/3.11/3.12)
│   ├── docker.yml      ← Docker 镜像构建
│   └── publish.yml     ← PyPI 发布
├── docs/               ← Sphinx 文档
├── tools/              ← 数据迁移脚本
└── examples/           ← 客户端示例
```

---

## 10. 安全要点

| 机制 | 实现 |
|---|---|
| 密码存储 | `werkzeug.security.generate_password_hash` (pbkdf2:sha256) |
| 密码读取 | `check_password_hash`，从 `User.password_hash` 统一读取 |
| 密码传输 | 前端 RSA-JWE 加密后传输，解密用 `decrypt_jwe_password()` |
| JWT 签名 | HMAC-SHA256 (内部 sid) + RS256 (ID Token) |
| API 错误 | `ApiError` 带正确 `status_code` (400/403)，AJAX error 回调处理 |
| 登出 | `Set-Cookie: sid=; expires=0` 清除 cookie |
| 密码泄露 | `list_users()` 和 `get_user_by_uid()` 排除 `password_hash` |
| 第三方 token | access_token 不入库，每次重新授权 |
| URL 安全 | `is_safe_url()` 防 open redirect |
| 验证码防刷 | 同一账号 60s 内不可重复发送，有效期 5 分钟 |
| 旧密码恢复 | 忘记密码 → 验证码登录 → 直接修改密码（无需旧密码验证） |
