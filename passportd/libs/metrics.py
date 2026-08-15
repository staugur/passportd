# -*- coding: utf-8 -*-
"""Prometheus 指标采集与导出模块。

提供以下四类指标：

- 进程指标：扫描所有 passportd/gunicorn 相关进程的 CPU 时间、内存、文件
  描述符等（基于 Linux /proc，非 Linux 环境仅采集当前进程）
- Python/GC 指标：当前进程的 GC 状态（``gc.get_count`` 待回收对象数、
  ``gc.get_threshold`` 阈值）及 prometheus_client 内置的 GC/平台指标
- Gunicorn 指标：worker 配置数、存活 worker 数、每个 worker 的 socket 连接数
- 业务指标：用户数、活跃会话数、OAuth 客户端数等（查询数据库，带缓存）
- 极验 bypass 指标：极验宕机降级状态（读 Redis 缓存，1=正常 / 0=宕机）
- 请求指标：请求计数（经 Redis 聚合到全 worker）、当前进程耗时直方图与
  并发请求数

指标端点默认为 ``GET /metrics``，支持可选的 ``METRICS_TOKEN`` Bearer
Token 鉴权。进程/业务/Redis 类指标的采集结果带有 TTL 缓存，避免每次抓取
都全量扫描数据库与 /proc。
"""

import gc as gc_module
import hmac
import os
import re
import resource
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

from flask import Blueprint, Response, g, request
from peewee import fn
from prometheus_client import (
    CollectorRegistry,
    Gauge,
    GCCollector,
    Histogram,
    PlatformCollector,
    generate_latest,
)
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from ..basis.common import now
from ..basis.conf import config
from ..basis.vars import GEETEST_BYPASS_REDIS_KEY, PROC_NAME
from ..models.model import (
    AuditLog,
    Auth,
    LoginRecord,
    OAuthAuthorization,
    OAuthClient,
    OAuthToken,
    PasskeyCredential,
    User,
    UserSession,
)
from ..utils.common import logger, rdb

__all__ = ["bp", "init_metrics"]

#: 进程扫描缓存（/proc 扫描开销较大，TTL 后重新扫描）
_process_cache: Dict[str, Any] = {"ts": 0.0, "data": []}
#: 业务指标缓存（数据库统计，TTL 后重新查询）
_biz_cache: Dict[str, Any] = {"ts": 0.0, "data": {}}
#: Redis INFO 缓存
_redis_cache: Dict[str, Any] = {"ts": 0.0, "data": {}}
#: 缓存锁，多线程下保护缓存读写
_cache_lock = threading.Lock()

#: Redis 中聚合请求计数的 Hash Key，格式 {method}:{status} -> count
_REQ_TOTAL_KEY = "{}:metrics:http_requests_total".format(PROC_NAME)
#: 本地请求计数兜底（Redis 不可用时输出）
_local_req_counter: Dict[Tuple[str, int], int] = {}
_local_req_lock = threading.Lock()

#: /proc 路径（仅 Linux 可用）
_PROC_DIR = "/proc"
#: CPU 时钟频率（每秒 tick 数）
_CLK_TCK = float(os.sysconf("SC_CLK_TCK")) if hasattr(os, "sysconf") else 100.0
#: 内存页大小
_PAGE_SIZE = (
    os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
)
#: 从 gunicorn 命令行解析 worker 数
_WORKERS_RE = re.compile(r"(?:-w|--workers)\s+(\d+)")

#: 指标注册表，独立于 prometheus_client 默认注册表，避免污染全局
REGISTRY = CollectorRegistry()

#: 内置收集器：python_info / python_gc_* （当前进程）
PlatformCollector(registry=REGISTRY)
GCCollector(registry=REGISTRY)

#: 当前进程请求耗时直方图
_HIST = Histogram(
    "passportd_http_request_duration_seconds",
    "HTTP 请求耗时（当前进程）",
    ["method", "endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)
#: 当前进程并发请求数
_INPROGRESS = Gauge(
    "passportd_http_requests_inprogress",
    "HTTP 并发请求数（当前进程）",
    ["pid"],
    registry=REGISTRY,
)

bp = Blueprint("metrics", __name__)


def _cache_ttl() -> float:
    """获取指标缓存 TTL（秒）。"""
    try:
        return float(config.get("METRICS_CACHE_TTL") or 30)
    except (TypeError, ValueError):
        return 30.0


def _read_proc(pid: int, name: str) -> Optional[str]:
    """读取 ``/proc/<pid>/<name>`` 文件内容。

    :param pid: 进程号
    :param name: proc 文件名称
    :returns: 文件内容，读取失败返回 None
    """
    try:
        with open(
            "{}/{}/{}".format(_PROC_DIR, pid, name),
            "r",
            encoding="utf-8",
            errors="ignore",
        ) as f:
            return f.read()
    except OSError:
        return None


def _read_proc_uptime() -> float:
    """读取系统启动以来的秒数（/proc/uptime 第一字段）。"""
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            return float(f.read().split()[0])
    except (OSError, IndexError, ValueError):
        return 0.0


def _parse_proc_stat(pid: int) -> Optional[Dict[str, Any]]:
    """解析 ``/proc/<pid>/stat`` 中进程的 CPU/内存相关字段。

    :param pid: 进程号
    :returns: 包含 comm/ppid/utime/stime/starttime/vsize/rss 的字典，
        失败返回 None
    """
    content = _read_proc(pid, "stat")
    if not content:
        return None
    try:
        lpar = content.find("(")
        rpar = content.rfind(")")
        if lpar < 0 or rpar < 0:
            return None
        comm = content[lpar + 1:rpar]
        # 去掉 "pid (comm)" 前缀后，字段从第 3 个（state）开始
        fields = content[rpar + 2:].split()
        return {
            "comm": comm,
            "ppid": int(fields[1]),
            "utime": int(fields[11]),
            "stime": int(fields[12]),
            "starttime": int(fields[19]),
            "vsize": int(fields[20]),
            "rss": int(fields[21]),
        }
    except (ValueError, IndexError):
        return None


def _detect_role(proc: Dict[str, Any], related_pids: set) -> str:
    """根据进程信息与进程间父子关系判断进程角色。

    gunicorn 加载应用时会调用 ``setproctitle(PROC_NAME)``（见 app.py）
    把进程标题改为 ``passportd``，导致 ``/proc/<pid>/comm`` 不再等于
    ``gunicorn``，且 ``/proc/<pid>/cmdline``（原始启动命令）也不含
    master/worker 字样，因此不能仅依赖这两个字段判断；worker 是
    master fork 出的子进程，通过 ppid 父子关系可可靠区分两者。

    :param proc: 进程信息（含 comm/cmdline/ppid 字段）
    :type proc: dict
    :param related_pids: 所有相关进程的 pid 集合
    :type related_pids: set
    :returns: gunicorn_master / gunicorn_worker / app
    :rtype: str
    """
    comm = proc["comm"]
    cmdline = proc["cmdline"]
    ppid = proc["ppid"]
    if "gunicorn" not in comm and "gunicorn" not in cmdline:
        return "app"
    if "master" in comm:
        return "gunicorn_master"
    if ppid in related_pids:
        return "gunicorn_worker"
    if "worker" in comm:
        return "gunicorn_worker"
    return "gunicorn_master"


def _is_related_process(comm: str, cmdline: str) -> bool:
    """判断进程是否为 passportd/gunicorn 相关进程。

    :param comm: 进程名
    :param cmdline: 命令行（空格分隔）
    :returns: True 表示相关
    """
    if comm in ("gunicorn", PROC_NAME):
        return True
    if PROC_NAME in cmdline:
        return True
    if "passportd.app" in cmdline or "passportd:app" in cmdline:
        return True
    return False


def scan_processes() -> List[Dict[str, Any]]:
    """扫描所有 passportd/gunicorn 相关进程（仅 Linux /proc 可用）。

    非 Linux 环境（如 macOS 开发机）返回空列表，调用方回退到当前进程。

    :returns: 进程信息字典列表
    :rtype: list[dict]
    """
    result: List[Dict[str, Any]] = []
    if not os.path.isdir(_PROC_DIR):
        return result
    uid = os.getuid() if hasattr(os, "getuid") else None
    for entry in os.listdir(_PROC_DIR):
        if not entry.isdigit():
            continue
        pid = int(entry)
        stat = _parse_proc_stat(pid)
        if not stat:
            continue
        cmdline = (_read_proc(pid, "cmdline") or "").replace("\x00", " ")
        if not _is_related_process(stat["comm"], cmdline):
            continue
        # 仅统计同用户进程，避免读到他人进程的数据
        if uid is not None:
            status = _read_proc(pid, "status") or ""
            m = re.search(r"^Uid:\s+(\d+)", status, re.M)
            if m and int(m.group(1)) != uid:
                continue
        # 文件描述符与 socket 连接数
        fd_dir = "{}/{}/fd".format(_PROC_DIR, pid)
        fds = socket_fds = 0
        if os.path.isdir(fd_dir):
            try:
                for fd in os.listdir(fd_dir):
                    fds += 1
                    try:
                        if os.readlink(
                            "{}/{}".format(fd_dir, fd)
                        ).startswith("socket:"):
                            socket_fds += 1
                    except OSError:
                        pass
            except OSError:
                pass
        # CPU 累计时间（秒）与进程启动时间戳
        cpu_seconds = (stat["utime"] + stat["stime"]) / _CLK_TCK
        uptime = _read_proc_uptime()
        start_relative = stat["starttime"] / _CLK_TCK
        start_time = time.time() - max(0.0, uptime - start_relative)
        result.append({
            "pid": pid,
            "ppid": stat["ppid"],
            "comm": stat["comm"],
            "cmdline": cmdline,
            "role": "app",
            "cpu_seconds": cpu_seconds,
            "rss_bytes": stat["rss"] * _PAGE_SIZE,
            "vms_bytes": stat["vsize"],
            "fds": fds,
            "socket_fds": socket_fds,
            "start_time": start_time,
        })
    # 角色判定依赖进程间的父子关系，收集齐全后统一计算
    related_pids = {p["pid"] for p in result}
    for p in result:
        p["role"] = _detect_role(p, related_pids)
    result.sort(key=lambda p: p["pid"])
    return result


def _cache_expired(cache: Dict[str, Any]) -> bool:
    """判断 TTL 缓存是否已过期。

    :param cache: 缓存字典，含 ts/data 字段
    :returns: True 表示需要刷新缓存
    """
    return cache["data"] is None or time.time() - cache["ts"] >= _cache_ttl()


def _get_scanned_processes() -> List[Dict[str, Any]]:
    """带 TTL 缓存的进程扫描结果。"""
    with _cache_lock:
        if _cache_expired(_process_cache):
            _process_cache["data"] = scan_processes()
            _process_cache["ts"] = time.time()
        return _process_cache["data"]


def _current_process_metrics() -> Dict[str, Any]:
    """获取当前进程的 CPU/内存指标（非 Linux 环境回退）。"""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "role": "app",
        "cpu_seconds": usage.ru_utime + usage.ru_stime,
        # macOS ru_maxrss 单位是字节，Linux 是 KB；此处仅开发环境参考
        "rss_bytes": usage.ru_maxrss,
        "vms_bytes": 0,
        "fds": 0,
        "socket_fds": 0,
        "start_time": 0,
    }


def _parse_workers_from_cmdline(cmdline: str) -> int:
    """从 gunicorn master 命令行解析配置的 worker 数。

    :param cmdline: master 进程命令行
    :returns: worker 数，无法解析返回 0
    """
    m = _WORKERS_RE.search(cmdline)
    if m:
        return int(m.group(1))
    env_workers = os.environ.get("WEB_CONCURRENCY", "")
    if env_workers.isdigit():
        return int(env_workers)
    return 0


class _ProcessCollector:
    """采集所有相关进程的 CPU/内存/文件描述符指标。"""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        procs = _get_scanned_processes()
        if not procs:
            procs = [_current_process_metrics()]
        cpu = GaugeMetricFamily(
            "passportd_process_cpu_seconds_total",
            "进程累计 CPU 时间（秒）",
            labels=["pid", "role"],
        )
        rss = GaugeMetricFamily(
            "passportd_process_resident_memory_bytes",
            "进程常驻内存（RSS，字节）",
            labels=["pid", "role"],
        )
        vms = GaugeMetricFamily(
            "passportd_process_virtual_memory_bytes",
            "进程虚拟内存（VMS，字节）",
            labels=["pid", "role"],
        )
        fds = GaugeMetricFamily(
            "passportd_process_open_fds",
            "进程打开的文件描述符数",
            labels=["pid", "role"],
        )
        sockets = GaugeMetricFamily(
            "passportd_process_socket_fds",
            "进程打开的 socket 描述符数",
            labels=["pid", "role"],
        )
        start = GaugeMetricFamily(
            "passportd_process_start_time_seconds",
            "进程启动时间戳（Unix 秒）",
            labels=["pid", "role"],
        )
        for p in procs:
            labels = [str(p["pid"]), p["role"]]
            cpu.add_metric(labels, p["cpu_seconds"])
            rss.add_metric(labels, p["rss_bytes"])
            vms.add_metric(labels, p["vms_bytes"])
            fds.add_metric(labels, p["fds"])
            sockets.add_metric(labels, p["socket_fds"])
            start.add_metric(labels, p["start_time"])
        yield cpu
        yield rss
        yield vms
        yield fds
        yield sockets
        yield start


class _GunicornCollector:
    """采集 gunicorn 部署相关指标（worker 数、存活数、连接数）。"""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        procs = _get_scanned_processes()
        master = [p for p in procs if p["role"] == "gunicorn_master"]
        workers = [p for p in procs if p["role"] == "gunicorn_worker"]
        configured = GaugeMetricFamily(
            "passportd_gunicorn_workers_configured",
            "gunicorn 配置的 worker 数",
        )
        alive = GaugeMetricFamily(
            "passportd_gunicorn_workers_alive",
            "当前存活的 gunicorn worker 数",
        )
        master_alive = GaugeMetricFamily(
            "passportd_gunicorn_master_alive",
            "gunicorn master 进程是否存活（1=存活）",
        )
        conns = GaugeMetricFamily(
            "passportd_gunicorn_worker_connections",
            "每个 gunicorn worker 的 socket 连接数",
            labels=["pid"],
        )
        workers_conf = 0
        for m in master:
            workers_conf = _parse_workers_from_cmdline(
                m.get("cmdline") or ""
            )
        configured.add_metric([], workers_conf)
        alive.add_metric([], len(workers))
        master_alive.add_metric([], 1 if master else 0)
        for w in workers:
            conns.add_metric([str(w["pid"])], w["socket_fds"])
        yield configured
        yield alive
        yield master_alive
        yield conns


class _GCStateCollector:
    """采集当前进程 GC 状态（待回收对象数与阈值）。"""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        pending = GaugeMetricFamily(
            "passportd_python_gc_objects_pending",
            "当前各代待回收对象数（gc.get_count）",
            labels=["generation"],
        )
        threshold = GaugeMetricFamily(
            "passportd_python_gc_threshold",
            "各代 GC 触发阈值（gc.get_threshold）",
            labels=["generation"],
        )
        for gen, count in enumerate(gc_module.get_count()):
            pending.add_metric([str(gen)], count)
        for gen, threshold_val in enumerate(gc_module.get_threshold()):
            threshold.add_metric([str(gen)], threshold_val)
        yield pending
        yield threshold


def _query_business_metrics() -> Dict[str, Any]:
    """查询业务指标（用户数、会话数、客户端数等）。

    :returns: 业务指标数据字典
    :rtype: dict
    """
    data: Dict[str, Any] = {}
    try:
        rows = (
            User.select(User.status, fn.COUNT(User.uid).alias("cnt"))
            .group_by(User.status)
            .tuples()
        )
        data["users_by_status"] = {str(s): c for s, c in rows}
    except Exception as e:  # 表缺失等，不影响其他指标
        logger.debug("metrics: query users failed: %s", e)

    try:
        sessions_active = UserSession.select(
            fn.COUNT(UserSession.session_key)
        ).where(UserSession.expire_time > now()).scalar()
        data["sessions_active"] = sessions_active or 0
        sessions_total = UserSession.select(
            fn.COUNT(UserSession.session_key)
        ).scalar()
        data["sessions_total"] = sessions_total or 0
    except Exception as e:
        logger.debug("metrics: query sessions failed: %s", e)

    try:
        rows = (
            Auth.select(Auth.classify, fn.COUNT(Auth.uid).alias("cnt"))
            .group_by(Auth.classify)
            .tuples()
        )
        data["auth_by_classify"] = {str(c): n for c, n in rows}
    except Exception as e:
        logger.debug("metrics: query auth failed: %s", e)

    for key, model in (
        ("oauth_clients", OAuthClient),
        ("oauth_authorizations", OAuthAuthorization),
        ("passkeys", PasskeyCredential),
        ("login_records", LoginRecord),
        ("audit_logs", AuditLog),
    ):
        try:
            data[key] = model.select(fn.COUNT(1)).scalar() or 0
        except Exception as e:
            logger.debug("metrics: query %s failed: %s", key, e)

    try:
        tokens_active = OAuthToken.select(fn.COUNT(1)).where(
            OAuthToken.status == 1
        ).scalar()
        data["oauth_tokens_active"] = tokens_active or 0
    except Exception as e:
        logger.debug("metrics: query tokens failed: %s", e)
    return data


def _get_business_metrics() -> Dict[str, Any]:
    """带 TTL 缓存的业务指标查询结果。"""
    with _cache_lock:
        if _cache_expired(_biz_cache):
            _biz_cache["data"] = _query_business_metrics()
            _biz_cache["ts"] = time.time()
        return _biz_cache["data"]


class _BusinessCollector:
    """采集业务指标（用户数、活跃会话数、OAuth 客户端数等）。"""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        data = _get_business_metrics()
        users = GaugeMetricFamily(
            "passportd_users_total",
            "用户总数",
            labels=["status"],
        )
        for status, count in data.get("users_by_status", {}).items():
            users.add_metric([status], count)

        identities = GaugeMetricFamily(
            "passportd_auth_identities_total",
            "认证身份数（按认证方式）",
            labels=["classify"],
        )
        for classify, count in data.get("auth_by_classify", {}).items():
            identities.add_metric([str(classify)], count)

        scalars = [
            (
                "passportd_sessions_active",
                "活跃会话数（未过期）",
                data.get("sessions_active", 0),
            ),
            (
                "passportd_sessions_total",
                "会话总数",
                data.get("sessions_total", 0),
            ),
            (
                "passportd_oauth_clients_total",
                "OIDC 客户端数",
                data.get("oauth_clients", 0),
            ),
            (
                "passportd_oauth_tokens_active",
                "有效 OAuth token 数",
                data.get("oauth_tokens_active", 0),
            ),
            (
                "passportd_oauth_authorizations_total",
                "OAuth 授权记录数",
                data.get("oauth_authorizations", 0),
            ),
            (
                "passportd_passkeys_total",
                "Passkey 凭证数",
                data.get("passkeys", 0),
            ),
            (
                "passportd_login_records_total",
                "登录记录总数",
                data.get("login_records", 0),
            ),
            (
                "passportd_audit_logs_total",
                "审计日志总数",
                data.get("audit_logs", 0),
            ),
        ]
        for name, desc, value in scalars:
            family = GaugeMetricFamily(name, desc)
            family.add_metric([], float(value))
            yield family

        yield users
        yield identities


def _query_redis_info() -> Dict[str, Any]:
    """查询 Redis INFO 关键字段。

    :returns: Redis INFO 字段字典
    :rtype: dict
    """
    try:
        return rdb.info()
    except Exception as e:
        logger.debug("metrics: redis info failed: %s", e)
        return {}


def _get_redis_info() -> Dict[str, Any]:
    """带 TTL 缓存的 Redis INFO 结果。"""
    with _cache_lock:
        if _cache_expired(_redis_cache):
            _redis_cache["data"] = _query_redis_info()
            _redis_cache["ts"] = time.time()
        return _redis_cache["data"]


class _RedisCollector:
    """采集 Redis 服务自身指标（内存、连接、命令数等）。"""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        info = _get_redis_info()
        if not info:
            return
        items = [
            (
                "passportd_redis_uptime_seconds",
                "Redis 运行时长（秒）",
                "uptime_in_seconds",
            ),
            (
                "passportd_redis_connected_clients",
                "Redis 客户端连接数",
                "connected_clients",
            ),
            (
                "passportd_redis_used_memory_bytes",
                "Redis 已用内存（字节）",
                "used_memory",
            ),
            (
                "passportd_redis_commands_processed_total",
                "Redis 累计处理命令数",
                "total_commands_processed",
            ),
            (
                "passportd_redis_connections_received_total",
                "Redis 累计接受连接数",
                "total_connections_received",
            ),
        ]
        for name, desc, key in items:
            value = info.get(key)
            if value is None:
                continue
            try:
                float_value = float(value)
            except (TypeError, ValueError):
                continue
            family = GaugeMetricFamily(name, desc)
            family.add_metric([], float_value)
            yield family


def _inc_http_requests(method: str, status: int) -> None:
    """累加请求计数：Redis Hash 聚合（全 worker）+ 当前进程本地计数。

    本地计数用于 Redis 不可用时兜底，也反映当前 worker 的实际处理量。

    :param method: HTTP 方法
    :param status: HTTP 状态码
    """
    try:
        rdb.hincrby(_REQ_TOTAL_KEY, "{}:{}".format(method, status), 1)
    except Exception as e:
        logger.debug("metrics: redis hincrby failed: %s", e)
    with _local_req_lock:
        _local_req_counter[(method, status)] = (
            _local_req_counter.get((method, status), 0) + 1
        )


class _GeetestBypassCollector:
    """采集极验 bypass 状态（1=正常，0=宕机降级）。

    状态值由 libs/geetest.py 的后台检测线程每 GEETEST_BYPASS_INTERVAL 秒
    请求极验 bypass 接口后写入 Redis（key 见 GEETEST_BYPASS_REDIS_KEY），
    此处仅读取并暴露为 Prometheus gauge。
    """

    def collect(self) -> Iterator[GaugeMetricFamily]:
        family = GaugeMetricFamily(
            "passportd_geetest_bypass_status",
            "极验行为验证 bypass 状态（1=正常, 0=宕机降级）",
            labels=["status"],
        )
        try:
            status = rdb.get(GEETEST_BYPASS_REDIS_KEY) or "fail"
        except Exception as e:
            logger.debug("metrics: geetest bypass status query failed: %s", e)
            status = "fail"
        if isinstance(status, bytes):
            status = status.decode("utf-8")
        family.add_metric(
            [status], 1.0 if status == "success" else 0.0
        )
        yield family


class _HttpRequestCollector:
    """采集请求计数（优先 Redis 聚合数据，失败回退本地）。"""

    def collect(self) -> Iterator[CounterMetricFamily]:
        family = CounterMetricFamily(
            "passportd_http_requests_total",
            "HTTP 请求总数（按 method/status）",
            labels=["method", "status"],
        )
        try:
            data = rdb.hgetall(_REQ_TOTAL_KEY)
        except Exception as e:
            logger.debug("metrics: redis hgetall failed: %s", e)
            data = {}
        samples: Dict[str, float] = {}
        if isinstance(data, dict) and data:
            for key, count in data.items():
                method, _, status = key.rpartition(":")
                try:
                    samples["{}:{}".format(method, status)] = float(count)
                except (TypeError, ValueError):
                    continue
        else:
            with _local_req_lock:
                for (method, status), count in sorted(
                    _local_req_counter.items()
                ):
                    samples["{}:{}".format(method, status)] = float(count)
        if not samples:
            # 完全无计数时输出零值系列，避免 Grafana 面板出现 no data
            samples["GET:200"] = 0.0
        for key, count in samples.items():
            method, _, status = key.rpartition(":")
            family.add_metric([method, status], count)
        yield family


#: 注册自定义收集器
REGISTRY.register(_ProcessCollector())
REGISTRY.register(_GunicornCollector())
REGISTRY.register(_GCStateCollector())
REGISTRY.register(_BusinessCollector())
REGISTRY.register(_RedisCollector())
REGISTRY.register(_GeetestBypassCollector())
REGISTRY.register(_HttpRequestCollector())


def _metrics_url() -> str:
    """计算完整的指标端点 URL（含 URI_PREFIX）。"""
    prefix = (config.get("URI_PREFIX") or "/").rstrip("/")
    path = config.get("METRICS_PATH") or "/metrics"
    return (prefix + path).rstrip("/") or "/"


def _is_metrics_request() -> bool:
    """判断当前请求是否为指标端点自身（不参与指标统计）。"""
    return request.path.rstrip("/") == _metrics_url()


def _text_response(body: str, status_code: int) -> Response:
    """构造纯文本响应。

    :param body: 响应内容
    :param status_code: HTTP 状态码
    :returns: Flask Response
    """
    response = Response(body, status=status_code)
    response.headers["Content-Type"] = (
        "text/plain; version=0.0.4; charset=utf-8"
    )
    return response


@bp.route("/metrics", methods=["GET"])
def metrics_view() -> Response:
    """Prometheus 指标导出端点。

    :returns: Prometheus 文本格式的指标数据
    :rtype: flask.Response
    """
    if not config.get("METRICS_ENABLED", True):
        return _text_response("metrics disabled", 503)
    token = config.get("METRICS_TOKEN") or ""
    if token:
        auth = request.headers.get("Authorization", "")
        provided = auth[7:] if auth.startswith("Bearer ") else ""
        if not provided or not hmac.compare_digest(provided, token):
            return _text_response("unauthorized", 401)
    body = generate_latest(REGISTRY).decode("utf-8")
    return _text_response(body, 200)


def init_metrics(app) -> None:
    """注册请求指标采集钩子（需 METRICS_ENABLED 为真）。

    :param app: Flask 应用实例
    :type app: flask.Flask
    """
    if not config.get("METRICS_ENABLED", True):
        return

    @app.before_request
    def _metrics_before_request():
        if _is_metrics_request():
            return
        _INPROGRESS.labels(pid=str(os.getpid())).inc()
        g._metrics_started = time.perf_counter()

    @app.after_request
    def _metrics_after_request(response):
        if _is_metrics_request():
            return response
        start = getattr(g, "_metrics_started", None)
        if start is not None:
            endpoint = request.endpoint or request.path
            _HIST.labels(request.method, endpoint).observe(
                time.perf_counter() - start
            )
        _inc_http_requests(request.method, response.status_code)
        return response

    @app.teardown_request
    def _metrics_teardown_request(exc=None):
        # 无论请求是否异常都释放并发计数，避免泄漏
        if getattr(g, "_metrics_started", None) is not None:
            _INPROGRESS.labels(pid=str(os.getpid())).dec()
