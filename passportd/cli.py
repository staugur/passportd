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

import os
import signal
import sys
import tempfile
import time
from contextlib import contextmanager
from json import JSONEncoder, dumps
from types import FunctionType

import click

from .basis.common import now
from .basis.conf import config as passportd_config
from .basis.vars import PROC_NAME


def _get_pidfile():
    """获取 gunicorn pid 文件路径。

    :returns: pid 文件完整路径，位于系统临时目录下
    :rtype: str
    """
    return os.path.join(tempfile.gettempdir(), f"{PROC_NAME}.pid")


def _read_pid():
    """读取 pid 文件中记录的进程 ID。

    :returns: 进程 ID 整数，若文件不存在或内容无效则返回 None
    :rtype: int or None
    """
    pidfile = _get_pidfile()
    if not os.path.isfile(pidfile):
        return None
    with open(pidfile) as f:
        try:
            return int(f.read().strip())
        except ValueError:
            return None


def _is_running(pid):
    """检测指定 pid 的进程是否存活。

    通过 ``os.kill(pid, 0)`` 发送空信号检测进程是否存在。

    :param pid: 进程 ID
    :type pid: int or None
    :returns: 进程存活返回 True，否则返回 False
    :rtype: bool
    """
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class ConfigEncoder(JSONEncoder):
    """自定义 JSON 编码器，将不可序列化的类型（如函数）转为字符串。"""

    def default(self, obj):
        """将不可序列化对象转为字符串表示。

        :param obj: 待序列化的对象
        :returns: 对象对应的字符串表示
        :rtype: str
        """
        if isinstance(obj, FunctionType):
            # 将函数转换为字符串表示
            return (
                f"<function {obj.__name__}>"
                if hasattr(obj, "__name__")
                else "<function>"
            )
        # 其他不可序列化的类型
        return str(obj)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli():
    """Passportd 命令行管理工具。

    提供初始化、运行开发服务器、启动生产服务器、查看状态、停止、重启、
    查看配置、用户角色管理等子命令。
    """
    pass


@cli.command()
def run():
    """启动 Flask 内置开发服务器（适用于本地调试）。"""
    from passportd.app import create_app

    server = create_app()
    server.config.update(ENV="development")
    server.run(
        host=passportd_config["HOST"],
        port=passportd_config["PORT"],
        debug=passportd_config["DEBUG"],
    )


@cli.command()
def start():
    """启动生产服务器：通过 ``gunicorn -c passportd.py`` 启动 gunicorn 进程。"""
    conf_path = os.path.join(os.path.dirname(__file__), "passportd.py")
    cmd = [
        sys.executable,
        "-m",
        "gunicorn",
        "-c",
        conf_path,
        "passportd.app:create_app()",
    ]
    os.execv(sys.executable, cmd)


@cli.command()
def status():
    """查看 gunicorn 进程状态（运行中 / 未运行 / 残留 pid 文件）。"""
    pidfile = _get_pidfile()
    pid = _read_pid()

    click.echo(f"PID file: {pidfile}")
    if not pid:
        click.secho("Status: NOT RUNNING (no pidfile)", fg="yellow")
        return
    if _is_running(pid):
        click.secho(f"Status: RUNNING (pid {pid})", fg="green")
    else:
        click.secho(f"Status: STALE (pidfile exists but pid {pid} not alive)", fg="red")


@cli.command()
def stop():
    """优雅停止 gunicorn（发送 SIGTERM），超时后强制 SIGKILL。

    等待最多 30 秒让进程自行退出，超时则发送 SIGKILL 强杀。
    """
    pid = _read_pid()
    if not pid:
        click.secho("Not running (no pidfile)", fg="yellow")
        return
    if not _is_running(pid):
        click.secho(f"Pid {pid} not alive, removing stale pidfile", fg="yellow")
        os.remove(_get_pidfile())
        return

    click.echo(f"Sending SIGTERM to pid {pid} ...")
    os.kill(pid, signal.SIGTERM)

    timeout = 30
    while timeout > 0:
        if not _is_running(pid):
            click.secho("Stopped.", fg="green")
            return
        time.sleep(1)
        timeout -= 1

    click.secho(f"Process didn't stop, sending SIGKILL ...", fg="red")
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    click.secho("Force killed.", fg="yellow")


@cli.command()
@click.confirmation_option(prompt="Are you sure to restart?")
def restart():
    """重启 gunicorn：先停止当前进程，再重新启动。"""
    pid = _read_pid()

    if pid and _is_running(pid):
        click.echo(f"Stopping pid {pid} ...")
        os.kill(pid, signal.SIGTERM)
        timeout = 30
        while timeout > 0 and _is_running(pid):
            time.sleep(1)
            timeout -= 1
        if _is_running(pid):
            click.secho("Failed to stop, aborting restart", fg="red")
            return

    # Re-invoke start (same process replacement)
    conf_path = os.path.join(os.path.dirname(__file__), "passportd.py")
    cmd = [
        sys.executable,
        "-m",
        "gunicorn",
        "-c",
        conf_path,
        "passportd.app:create_app()",
    ]
    os.execv(sys.executable, cmd)


@cli.command()
def config():
    """打印当前服务端完整配置（JSON 格式，函数类型转为字符串显示）。"""
    click.echo(dumps(passportd_config, cls=ConfigEncoder, indent=4))


@cli.group()
def role():
    """管理用户角色（admin / superadmin），支持列出与设置。"""
    pass


def _get_user_or_exit(uid):
    """按 uid 查找用户，不存在则抛出异常退出。

    :param uid: 用户唯一标识符（22 位字符串）
    :returns: User 模型实例
    :raises click.ClickException: 用户不存在时抛出
    """
    from .models.model import User

    user = User.get_or_none(User.uid == uid)
    if user is None:
        raise click.ClickException(f"user {uid} not found")
    return user


def _normalize_roles(role_args):
    """归一化并校验角色参数。

    内置角色统一为小写（admin / superadmin / user），客户端角色
    （``ClientName:Role``）原样保留。

    :param role_args: 角色参数元组（可包含多个角色）
    :returns: 规范化后的角色列表
    :raises click.ClickException: 含非法角色时抛出
    """
    # 延迟导入避免 CLI 帮助信息加载时引入重依赖
    from .utils.common import is_valid_user_role

    roles = []
    for raw in role_args:
        # 内置角色统一小写，客户端角色（ClientName:Role）原样保留
        norm = raw.lower() if ":" not in raw else raw
        if not is_valid_user_role(norm):
            raise click.ClickException(f"invalid role: {raw}")
        roles.append(norm)
    return roles


@contextmanager
def _db_conn():
    """打开数据库连接，命令执行结束后关闭（CLI 场景使用）。"""
    from .models.model import db

    db.connect(reuse_if_open=True)
    try:
        yield
    finally:
        db.close()


@role.command("list")
@click.option(
    "--role",
    "role_filter",
    type=click.Choice(["admin", "superadmin"]),
    default=None,
    help="仅列出指定角色（默认同时列出 admin 与 superadmin）",
)
def role_list(role_filter):
    """列出所有管理员（admin / superadmin）。"""
    from .models.model import User

    with _db_conn():
        admins = [
            u
            for u in User.select()
            if any(r in ("admin", "superadmin") for r in (u.role or "").split())
        ]
        if role_filter:
            admins = [u for u in admins if role_filter in (u.role or "").split()]
        if not admins:
            click.echo("No admin user found")
            return
        click.echo(
            "{:<24} {:<24} {:<40} {}".format("UID", "NICKNAME", "ROLE", "STATUS")
        )
        for u in admins:
            click.echo(
                "{:<24} {:<24} {:<40} {}".format(u.uid, u.nickname, u.role, u.status)
            )


@role.command("set")
@click.argument("uid")
@click.argument("roles", nargs=-1, required=True)
def role_set(uid, roles):
    """将用户角色替换为指定角色。

    多个角色用空格分隔，如 ``passportd role set <uid> superadmin admin``。
    """
    from .models.audit import record_audit_log

    norm_roles = _normalize_roles(roles)
    with _db_conn():
        u = _get_user_or_exit(uid)
        u.role = " ".join(norm_roles)
        u.mtime = now()
        u.save()
        record_audit_log(
            uid=u.uid, action="role_set", detail={"roles": u.role}
        )
    click.secho(f"set {uid} role -> {u.role}", fg="green")


@role.command("add")
@click.argument("uid")
@click.argument("roles", nargs=-1, required=True)
def role_add(uid, roles):
    """向用户追加角色（已存在的角色自动去重）。"""
    from .models.audit import record_audit_log

    norm_roles = _normalize_roles(roles)
    with _db_conn():
        u = _get_user_or_exit(uid)
        current = (u.role or "").split()
        for r in norm_roles:
            if r not in current:
                current.append(r)
        u.role = " ".join(current)
        u.mtime = now()
        u.save()
        record_audit_log(
            uid=u.uid,
            action="role_add",
            detail={"added": norm_roles, "roles": u.role},
        )
    click.secho(f"add {uid} role -> {u.role}", fg="green")


@role.command("remove")
@click.argument("uid")
@click.argument("roles", nargs=-1, required=True)
def role_remove(uid, roles):
    """从用户移除指定角色。"""
    from .models.audit import record_audit_log

    norm_roles = _normalize_roles(roles)
    with _db_conn():
        u = _get_user_or_exit(uid)
        current = (u.role or "").split()
        for r in norm_roles:
            if r in current:
                current.remove(r)
        u.role = " ".join(current)
        u.mtime = now()
        u.save()
        record_audit_log(
            uid=u.uid,
            action="role_remove",
            detail={"removed": norm_roles, "roles": u.role},
        )
    click.secho(f"remove {uid} role -> {u.role}", fg="green")


@cli.command("create-superadmin")
@click.argument("account")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help="登录密码（6-32 位）",
)
@click.option("--nickname", default="", help="用户昵称（可选）")
def create_superadmin(account, password, nickname):
    """创建一个角色为 superadmin 的新用户（仅 username 账号）。

    账号必须是合法用户名（小写字母开头，3-32 位小写字母/数字/下划线），
    密码 6-32 位，仅用于创建初始超级管理员，不修改现有用户。
    """
    from .basis.errors import AuthError, ParamError
    from .models.audit import record_audit_log
    from .models.user import add_profile, get_account
    from .utils.common import username_check

    if not username_check(account):
        raise click.ClickException("invalid username")
    try:
        with _db_conn():
            add_profile(
                account, password, nickname=nickname, role="superadmin"
            )
            record_audit_log(
                uid=get_account(account)["uid"],
                action="role_set",
                detail={"roles": "superadmin"},
            )
    except (ParamError, AuthError) as e:
        raise click.ClickException(str(e))
    click.secho(f"created superadmin: {account}", fg="green")


if __name__ == "__main__":
    cli()
