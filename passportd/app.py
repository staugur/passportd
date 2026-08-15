# -*- coding: utf-8 -*-
"""
Copyright 2021 Hiroshi.tao

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from .basis.common import auto_create_data_dir, raise_version
from .basis.conf import config
from .utils.common import auto_init_rsa_key

__author__ = "Hiroshi.tao <me@tcw.im>"
__date__ = "2021-06-25"

raise_version()
auto_create_data_dir(config["DATA_DIR"])
auto_init_rsa_key()


def create_app():
    """创建并配置 Flask 应用实例。

    初始化应用的核心组件，包括：
    - 配置加载与代理信任
    - 蓝图注册（根路由、插件管理器）
    - OAuth2 客户端和 OIDC 服务端初始化
    - 插件加载（GitHub、Gitee OAuth2）
    - 请求前后处理钩子（数据库连接、用户状态解析、错误处理）

    :returns: 配置完成的 Flask 应用实例
    :rtype: flask.Flask
    """
    from flask import Flask, g, request, jsonify, render_template
    from flask_pluginkit import PluginManager, JsonResponse, blueprint
    from werkzeug.middleware.proxy_fix import ProxyFix

    from .basis.vars import PROC_NAME
    from .basis.conf import config
    from .basis.errors import ApiError
    from .basis.common import new_res, is_passkey_enabled
    from .utils.common import logger
    from .utils.web import parse_user_state
    from .models.model import db
    from .views.root import root
    from .views.oidc import server as OIDCServer
    from .libs.oidc import OIDCClient, oidc_save_token
    from .libs.interface import OAuthClient
    from .libs.geetest import geetest_enabled

    try:
        from setproctitle import setproctitle

        setproctitle(PROC_NAME)
    except ImportError:
        pass

    app = Flask(__name__)
    app.response_class = JsonResponse
    app.config.update(config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_for=1)
    app.register_blueprint(root, url_prefix=config.get("URI_PREFIX"))
    app.register_blueprint(blueprint, url_prefix="/pluginmanager")

    OAuthClient.init_app(app)
    OIDCServer.init_app(
        app,
        query_client=lambda client_id: OIDCClient(client_id),
        save_token=oidc_save_token,
    )
    PluginManager(
        app,
        logger=logger,
        plugin_packages=(
            "passportd.modules.oauth2_github",
            "passportd.modules.oauth2_gitee",
            "passportd.modules.oauth2_weibo",
            "passportd.modules.oauth2_qq",
            "passportd.modules.oauth2_google",
        ),  # type: ignore
    )

    @app.before_request
    def br():
        """在每个请求前解析用户登录态。"""
        #: 每个请求从连接池获取一个数据库连接，复用当前线程已有连接。
        db.connect(reuse_if_open=True)
        #: signin:bool -- 用户是否已登录
        #: user:dict  -- uid, account 等用户信息
        g.signin, g.user = parse_user_state()
        #: passkey_enabled:bool -- Passkey 功能是否已配置有效域名
        g.passkey_enabled = is_passkey_enabled(
            (config.get("PASSKEY_RP_ID") or "").strip()
        )
        g.geetest_enabled = geetest_enabled()

    @app.after_request
    def ar(response):
        """在每个响应后追加 CORS 头，允许 Authorization 请求头跨域访问。"""
        response.headers["Access-Control-Allow-Headers"] = "Authorization"
        return response

    @app.teardown_request
    def _db_close(exc=None):
        """请求结束后将连接归还连接池，确保不泄露。"""
        if not db.is_closed():
            db.close()

    @app.errorhandler(500)
    @app.errorhandler(404)
    @app.errorhandler(403)
    def handle_error(e):
        """统一 HTTP 错误处理：500 记录日志，API 返回 JSON，页面返回 error.j2 模板。

        :param e: HTTP 异常对象
        :type e: werkzeug.exceptions.HTTPException
        :returns: JSON 响应（API 路径）或 HTML 错误页面
        """
        if getattr(e, "code", None) == 500:
            logger.error(e, exc_info=True)
        code = e.code
        name = e.name
        if "/api/" in request.path:
            return jsonify(new_res()), code
        else:
            return render_template("error.j2", code=code, name=name), code

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        """捕获 ApiError 异常，返回结构化 JSON 错误响应。

        :param e: ApiError 异常实例
        :type e: passportd.basis.errors.ApiError
        :returns: JSON 错误响应
        """
        response = jsonify(e.to_dict())
        response.status_code = e.status_code
        return response

    from .libs.metrics import init_metrics

    init_metrics(app)

    return app
