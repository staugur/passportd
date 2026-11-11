# -*- coding: utf-8 -*-
"""
Copyright 2025 Hiroshi.tao

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

后台管理页面视图（概览、用户管理、OIDC 应用管理、审计与登录记录），
仅 admin / superadmin 角色可访问；高危操作按 superadmin 细分。
"""

from flask import (
    Blueprint,
    abort,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from ..models.stats import get_admin_stats
from ..models.user import is_admin, is_superadmin
from ..utils.web import get_redirect_url

bp = Blueprint("admin", "admin")


@bp.before_request
def require_admin():
    """后台蓝图统一鉴权：未登录跳转登录页，非管理员返回 403。

    仅在本蓝图的路由请求中执行，管理员判定不下沉到全局请求钩子，
    避免为每个请求（含 API、静态资源等）都查询用户角色。
    """
    if not g.signin:
        return redirect(get_redirect_url(next=request.url))
    uid = g.user.get("uid", "")
    if not is_admin(uid):
        abort(403)
    #: 供后台模板使用，仅在后台请求上下文中存在
    g.is_admin = True
    g.is_superadmin = is_superadmin(uid)


@bp.get("/")
def index():
    """后台首页：重定向到数据概览页面。"""
    return redirect(url_for(".dashboard"))


@bp.get("/dashboard")
def dashboard():
    """后台数据概览页面。"""
    use_cache = not request.args.get("refresh")
    return render_template(
        "admin_dashboard.j2", stats=get_admin_stats(use_cache=use_cache)
    )


@bp.get("/users")
def users():
    """后台用户管理页面（筛选、排序、角色管理与详情）。"""
    return render_template("admin_users.j2")


@bp.get("/clients")
def clients():
    """后台 OIDC 应用管理页面（只读详情、内部标记与删除）。"""
    return render_template("admin_clients.j2")


@bp.get("/logs")
def logs():
    """后台审计日志与登录记录页面。"""
    return render_template("admin_logs.j2")
