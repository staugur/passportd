# -*- coding: utf-8 -*-
"""
Passportd gunicorn 生产服务器配置文件。

配置项包括绑定地址、进程名称、工作进程数、日志级别等。
所有可调参数从 ``passportd.basis.conf`` 和 ``passportd.basis.vars`` 导入。
"""

import tempfile
from os.path import isdir, join
from multiprocessing import cpu_count

from passportd.basis.common import is_true
from passportd.basis.conf import config as cfg
from passportd.basis.vars import PROC_NAME

bind = "{host}:{port}".format(host=cfg["HOST"], port=cfg["PORT"])
proc_name = PROC_NAME
pidfile = join(tempfile.gettempdir(), f"{PROC_NAME}.pid")
backlog = 2048
workers = 4 if cpu_count() > 4 else cpu_count()
worker_class = "gevent"
worker_connections = 1000
max_requests = 10000
if isdir("/dev/shm"):
    worker_tmp_dir = "/dev/shm"

daemon = not is_true(cfg.get("NO_DAEMON"))
loglevel = cfg["LOG_LEVEL"]
accesslog = None
