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
import time
import tempfile

import click
from json import JSONEncoder, dumps
from types import FunctionType

from .basis.vars import PROC_NAME
from .basis.conf import config as passportd_config


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

    提供初始化、运行开发服务器、启动生产服务器、
    查看状态、停止、重启、查看配置等子命令。
    """
    pass


@cli.command()
def run():
    """启动 Flask 内置开发服务器（适用于本地调试）。"""
    from passportd.app import create_app

    server = create_app()
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


if __name__ == "__main__":
    cli()
