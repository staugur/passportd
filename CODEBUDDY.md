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
├── tests/              ← pytest 测试
├── docs/               ← Sphinx 文档 + changelog.rst
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
- 注释使用英文，项目文档（ARCH.md / changelog.rst）使用中文
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
- URL 生成统一用 `url_for()`，不硬编码路径

## 变更记录

- **每次新增功能、修复问题或行为变更，必须同步更新 `docs/changelog.rst`**
- 格式参考已有条目：版本号标题 + 分类（``新特性``/``修复``/``变更``）+ 简要描述
- 版本号使用 `v<major>.<minor>.<patch>` 格式，如 ``v2.6.0``

```rst
v2.7.0
------

新特性
~~~~

- 新增 XXX 功能，支持 YYY。

修复
~~~~

- 修复 ZZZ 情况下 WWW 的问题。
```

## 持续集成 / 质量

- 代码格式化：`make lint`（flake8 + isort）
- 测试：`make test`（pytest，Python 3.10/3.11/3.12）
- 修改代码后需保持零 lint 错误，保证导入不失败
