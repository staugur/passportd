# passportd — 项目上下文

passportd 是一个 OIDC/OAuth2 统一认证服务（Flask + Peewee ORM + Redis + JWT），
同时承担 OAuth2 Client（对接 GitHub/Gitee/QQ/微博）和 OIDC Server（签发 SSO 令牌）两种角色。

技术栈：Python 3.10+, Flask, Peewee ORM, authlib, Redis, joserfc (JWT)
前端：Bulma CSS + FontAwesome + jQuery + Jinja2 模板
详细架构见 `ARCH.md`。

## 目录结构

```
passportd/
├── app.py              ← Flask 应用工厂
├── version.py          ← 版本号
├── basis/              ← 基础设施层 (conf, errors, vars, common, mixin)
├── models/             ← Peewee ORM 模型 + 业务逻辑 ★
├── views/              ← Flask Blueprint 路由 (front/api/oidc)
├── libs/               ← 核心库 (oidc, interface)
├── utils/              ← 工具 (web, common)
├── modules/            ← OAuth2 第三方插件
├── templates/          ← Jinja2 模板 (.j2)
├── static/             ← 静态资源
├── tests/              ← unittest 测试
├── docs/               ← Sphinx 文档
└── requirements/       ← pip 依赖 (base/dev/prod/docs)
```

## Python 编码规范

### 基本风格

- 严格遵循 **PEP 8**，行宽上限 79 字符（见 setup.cfg flake8/pycodestyle 配置）
- 文件头 `# -*- coding: utf-8 -*-`
- 缩进 4 空格，不使用 Tab
- 文件末尾保留一个空行

### 导入顺序

按以下顺序分组，组间空一行：
1. 标准库 (os, json, datetime...)
2. 第三方库 (flask, peewee, redis...)
3. 项目内部 (passportd.* / ..basis.* / ..models.* / ..utils.*)

每组内按字母序排列。`from ... import ...` 放在 `import ...` 之后。

如果有循环导入风险，允许在函数内延迟导入模块。

```python
# 正确示例
import json
import os

from flask import Blueprint, g, render_template, request

from ..basis.errors import ParamError
from ..models.user import add_profile, login
```

### 命名规范

| 类型 | 风格 | 示例 |
|------|------|------|
| 模块/文件 | snake_case | `user.py`, `web_utils.py` |
| 类 | PascalCase | `UserSession`, `OAuthInterface` |
| 函数/方法 | snake_case | `create_session()`, `parse_user_agent()` |
| 变量 | snake_case | `session_key`, `user_agent` |
| 常量 | UPPER_SNAKE_CASE | `SECRET_KEY`, `JWT_ALGORITHM` |
| 私有成员 | 前缀单下划线 | `_parse_device_name()` |

### 类型注解

- 公共函数/方法必须标注参数类型和返回值类型
- 使用 `typing` 模块：`Optional`, `Union`, `dict`, `list`, `tuple`, `Callable`, `Any`
- `None` 返回值标注为 `-> None`

```python
from typing import Any, Optional

def get_user_by_uid(uid: str) -> Optional[dict[str, Any]]:
    """根据 uid 获取用户信息，不存在返回 None。"""
    ...
```

### 注释与文档

- **模块级**：文件开头用 `"""模块功能简述"""` 描述模块职责
- **类和函数**：使用 docstring (三重双引号)，采用 **Sphinx RST** 格式，使用 `:param:`, `:type:`, `:returns:`, `:raises:` 等指令
- 复杂逻辑用行内注释 `#` 解释意图，不要注释代码做了什么（代码本身说明了）
- 注释使用英文，项目文档（ARCH.md / CHANGELOG.rst）使用中文
- 项目文档（`docs/` 目录）使用 **Sphinx + reStructuredText**，文件后缀 `.rst`

```python
def login(account: str, credential: str) -> dict:
    """验证账号密码并返回用户信息。

    :param account: 登录账号（用户名/邮箱/手机号）
    :param credential: 密码原文（前端已 RSA 加密，此方法内解密）
    :returns: 包含 uid, account, nickname 等字段
    :rtype: dict
    :raises AuthError: 账号不存在或密码错误
    """
    ...
```

### 异常处理

- 使用项目定义的异常类：`AuthError`, `JWTError`, `ParamError`, `ApiError`
- API 路由使用 `ApiError`，带正确的 HTTP status_code
- 不允许裸 `except:`，至少 `except Exception:`
- 外部调用（Redis、HTTP）需捕获特定异常并转换为项目异常

### API 错误规范

**后端英文 + 错误码，前端映射中文**（v2.7.0 起强制）：

- `ApiError` 构造签名：`ApiError(message, code, success=False, status_code=200)`，抛错时**必须**携带英文 `message` 和合适的 `code`
- 错误码从 `basis/errors.py` 的 `ErrorCode` 常量类中选取（如 `PARAM_ERROR` / `LOGIN_FAILED` / `VCODE_INVALID`），禁止硬编码新字符串
- 响应格式统一为 `{"success": false, "code": "VCODE_INVALID", "message": "invalid verification code"}`，前端通过 `res.code` 判断而非 `res.message`
- 将 `str(e)` 转换为 `ApiError` 时，按异常类型映射对应的错误码
- 存量 `ApiError("msg")` 不传 code 时 `code=""`，前端回退显示 `message`，保持兼容

前端联动：

- 新增/修改错误码时，必须同步更新 `templates/layout.j2` 中的 `ERROR_ZH` 映射表和 `apiMessage(res, fallback)` 兜底文案
- 模板中提示错误统一用 `apiMessage(res, '兜底文案')` 取中文提示，不直接使用 `res.message`
- 浏览器原生错误（如 WebAuthn `err.message`，非 API 响应）保持原样

### 数据库操作

- 使用 Peewee ORM，模型定义在 `models/model.py`
- 在请求上下文中通过 `db.connect(reuse_if_open=True)` 获取连接
- 写操作事物化，确保一致性
- 查询用 `.get_or_none()` 处理不存在的情况，不直接 `.get()`

### 其他

- 不使用 `print()` 做日志，统一用 Flask `app.logger` 或 `logging`
- 敏感数据（密码、token）不写入日志
- 配置通过 `basis/conf.py` 的 `config` 对象访问

## 前端规范 (JavaScript / Jinja2)

### JavaScript

- **变量定义必须使用 `let`**，禁止使用 `var`
- 常量使用 `const`
- 使用 `===` / `!==` 而不是 `==` / `!=`
- 字符串拼接优先使用模板字符串或保留 `+` 拼接方式，保持代码风格统一
- 函数命名使用 camelCase
- 避免全局变量污染，在 IIFE 或模块作用域内编写
- 禁止在 HTML 属性中写内联 JS（如 `onclick="..."`），使用 jQuery 事件绑定
- 不写 `console.log` 调试日志（生产代码中）

```javascript
// 正确
let $box = $('#sessions-box');
let sessionKey = response.data.session_key;

// 错误
var $box = $('#sessions-box');
```

### jQuery / 选择器

- jQuery 对象变量前缀 `$`：`let $list = $('#my-list');`
- 操作 DOM 时对用户输入使用 `$('<span>').text(userInput).html()` 防 XSS

### Jinja2 模板

- 模板文件后缀 `.j2`
- 使用 `{# 注释 #}` 进行模板注释
- 模板中的 Python 变量使用 `{{ var }}`，需注意转义
- 服务端数据注入 JS 用 `{{ var | tojson }}`，配合 `const` 声明真正的常量（如内部客户端名单 `INTERNAL_CLIENTS`）
- URL 生成统一用 `url_for()`，不硬编码路径
- 页脚结构：`layout.j2` 的 `footer.footer` **无背景色**、仅保留版权文字；公告栏 `#notice-bar` 是 `<body>` 级独立区块（位于 `<main>` 与 `<footer>` 之间），与页脚相互分离且同样无背景色，公告由 JS 异步渲染并支持逐条关闭

## OIDC 认证约定

### 客户端 scope 白名单

- 客户端可申请的 scope 白名单来自数据库的 `OAuthClient.scope` 字段（即创建客户端时勾选的范围）；授权请求的 `scope` 会与之**求交集**，不在白名单内的 scope 被**静默丢弃且不报错**（`libs/oidc.py` 的 `OIDCClient.get_allowed_scope()` 返回过滤后的字符串，永不为 `None`，因此 authlib 的 `InvalidScopeError` 分支不会触发）
- `basis/vars.py` 的 `OIDC_SUPPORTED_SCOPES` 仅用于 Discovery 文档的 `scopes_supported` 声明，**不是**授权校验的白名单
- scope 分层输出：`openid` → 仅 `sub`；`+ profile` → 昵称/头像等；`+ email` → 邮箱；`+ role` → 平台角色

### 平台角色（role scope）双条件门控

输出用户平台角色必须**同时**满足两个条件：

1. 客户端 `OAuthClient.scope` 含 `role`
2. 客户端 name 在配置 `OIDC_INTERNAL_CLIENTS`（英文逗号分隔，容忍逗号两侧空格）内

- 名称集合统一由 `libs/oidc.py` 的 `internal_client_names()` 解析，判断入口为 `_is_internal_client()`，禁止在别处重复解析该配置
- 仅输出平台内置角色（小写 `admin` / `superadmin` / `user`），`ClientName:Role` 格式的客户端角色会被 `_platform_roles()` 过滤；用户无内置角色时兜底 `user`
- 判定发生在 ID Token（`generate_user_info`）与 `/oidc/userinfo` 两处，**两处逻辑必须保持一致**
- 修改客户端 scope 后已签发的 token 不会自动升级，需重新走一次授权流程

### 管理页面 role 选项

- `templates/oidc.j2` 中 role 是普通复选框（`name="scope" value="role"`，非隐藏字段），仅当「应用名称」输入值命中 `INTERNAL_CLIENTS` 时才显示，显隐函数为 `toggleRoleScopeField()`
- 该名称列表由 `views/front.py` 的 `oidc_client` 视图通过 `internal_clients` 变量注入模板
- 非内部应用若库中已有 `role`，编辑时复选框仍会被自动勾选，提交后保留，避免误删

## 变更记录

- **每次新增功能、修复问题或行为变更，必须同步更新 `CHANGELOG.rst`（项目根目录）**
- 版本号使用 `v<major>.<minor>.<patch>` 格式，如 ``v2.6.0``
- 版本标题 + 分类（``新特性``/``修复``/``变更``），条目**精简概括、不要具体**：每条只写一句概括性描述，**禁止堆砌实现细节**（函数名、字段名、错误码、Redis key、TTL、接口路径、SQL 字段、Grafana 指标名等）、文件路径或实现过程
- 例外仅限：①用户可直接使用的入口（如 CLI 命令名 ``create-superadmin``）；②数据库模型变更必须附带对应 SQL（``.. code-block:: sql``）
- **修改数据库模型（新增/删除/修改字段）时，必须在 changelog 中附带对应 SQL 语句**（ALTER TABLE / CREATE TABLE 等），使用 ``.. code-block:: sql`` 指令

```rst
v2.7.0
------

新特性
~~~~

- 新增 XXX 功能，支持 YYY。

.. code-block:: sql

   ALTER TABLE some_table ADD COLUMN new_field VARCHAR(64) NOT NULL DEFAULT '';

修复
~~~~

- 修复 ZZZ 情况下 WWW 的问题。
```

## 持续集成 / 质量

- 代码检查：flake8 + isort（配置见 `setup.cfg`，行宽上限 79）。Makefile 当前**没有** lint 目标，直接运行 `.venv/bin/python -m flake8 <path>` 与 `.venv/bin/python -m isort --check-only <path>`
- 仓库存在少量历史告警（`E501` / `W503` 等），改动后对比报错数**不增加**即可，不要求清零
- 测试：`make test`（unittest：`python -m unittest discover`，Python 3.10/3.11/3.12，不依赖 pytest）
- 修改代码后需保证导入不失败
