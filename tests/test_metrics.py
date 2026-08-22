# -*- coding: utf-8 -*-
"""Prometheus 指标端点测试。

测试范围（libs/metrics.py + /metrics 路由）：
- GET  /metrics            指标端点返回 200 且包含核心指标
- METRICS_ENABLED=False    端点返回 503
- METRICS_TOKEN            无 Token 返回 401，带 Token 返回 200
- 进程扫描与 GC/业务指标数据可正常生成
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

# ---- Mock Redis（必须在导入 passportd 之前） ----
_mock_redis = MagicMock()
_mock_redis.get.return_value = None
_mock_redis.setex.return_value = True
_mock_redis.exists.return_value = False
_mock_redis.delete.return_value = True
_mock_redis.ping.return_value = True
_mock_redis.hgetall.return_value = {"GET:200": "1"}
_mock_redis.info.return_value = {
    "uptime_in_seconds": "100",
    "connected_clients": "2",
    "used_memory": "1024",
}

_mock_redis_module = MagicMock()
_mock_redis_module.Redis = MagicMock(return_value=_mock_redis)
_mock_redis_module.Redis.from_url = MagicMock(return_value=_mock_redis)
_mock_redis_module.from_url = MagicMock(return_value=_mock_redis)
sys.modules["redis"] = _mock_redis_module
sys.modules["redis.client"] = MagicMock()

# ---- 导入 passportd ----
from passportd.app import create_app  # noqa: E402
from passportd.basis.conf import config  # noqa: E402
from passportd.models.model import (  # noqa: E402
    AuditLog,
    Auth,
    LoginRecord,
    OAuthAuthorization,
    OAuthClient,
    OAuthToken,
    PasskeyCredential,
    User,
    UserSession,
    db,
)

#: /metrics 响应中应包含的核心指标
_CORE_METRICS = (
    "python_info",
    "python_gc_objects_collected_total",
    "passportd_python_gc_objects_pending",
    "passportd_process_cpu_seconds_total",
    "passportd_process_resident_memory_bytes",
    "passportd_gunicorn_workers_alive",
    "passportd_http_requests_total",
    "passportd_http_request_duration_seconds",
    "passportd_users_total",
    "passportd_sessions_active",
    "passportd_oauth_clients_total",
    "passportd_redis_used_memory_bytes",
)


class MetricsTest(unittest.TestCase):
    """Prometheus 指标端点测试"""

    @classmethod
    def setUpClass(cls):
        app = create_app()
        app.config["TESTING"] = True
        cls.app = app
        with app.app_context():
            if db.is_closed():
                db.connect()
            db.create_tables(
                [
                    User,
                    Auth,
                    OAuthClient,
                    OAuthToken,
                    OAuthAuthorization,
                    LoginRecord,
                    PasskeyCredential,
                    AuditLog,
                    UserSession,
                ],
                safe=True,
            )

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.close()

    def setUp(self):
        self.client = self.app.test_client()

    def test_metrics_endpoint_returns_core_metrics(self):
        """/metrics 返回 200 且包含核心指标"""
        resp = self.client.get("/metrics")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp.headers.get("Content-Type", ""))
        body = resp.data.decode("utf-8")
        for name in _CORE_METRICS:
            self.assertIn(name, body, "missing metric: {}".format(name))

    def test_metrics_request_counts_normal_api(self):
        """普通 API 请求会增加请求计数，/metrics 自身不计入"""
        # 本地兜底：hgetall 返回空时走本地计数，先请求一次普通接口
        _mock_redis.hgetall.return_value = {}
        resp = self.client.get("/api/key")
        self.assertEqual(resp.status_code, 200)
        body = self.client.get("/metrics").data.decode("utf-8")
        # 本地计数包含刚发生的 GET /api/key
        self.assertIn(
            'passportd_http_requests_total{method="GET",status="200"}',
            body,
        )
        # 本地计数仅反映当前进程，值至少为 1
        pattern = r'passportd_http_requests_total\{[^}]*status="200"[^}]*\} '
        self.assertRegex(body, pattern + r'[0-9]+\.0')
        _mock_redis.hgetall.return_value = {"GET:200": "1"}

    def test_metrics_disabled_returns_503(self):
        """METRICS_ENABLED=False 时端点返回 503"""
        old = config.get("METRICS_ENABLED")
        config["METRICS_ENABLED"] = False
        try:
            app = create_app()
            app.config["TESTING"] = True
            resp = app.test_client().get("/metrics")
            self.assertEqual(resp.status_code, 503)
        finally:
            config["METRICS_ENABLED"] = old

    def test_metrics_token_auth(self):
        """METRICS_TOKEN 配置后需要 Bearer Token 鉴权"""
        old = config.get("METRICS_TOKEN")
        config["METRICS_TOKEN"] = "secret-token"
        try:
            app = create_app()
            app.config["TESTING"] = True
            client = app.test_client()
            resp = client.get("/metrics")
            self.assertEqual(resp.status_code, 401)
            resp = client.get(
                "/metrics",
                headers={"Authorization": "Bearer secret-token"},
            )
            self.assertEqual(resp.status_code, 200)
            resp = client.get(
                "/metrics",
                headers={"Authorization": "Bearer wrong-token"},
            )
            self.assertEqual(resp.status_code, 401)
        finally:
            config["METRICS_TOKEN"] = old

    def test_business_metrics_query(self):
        """业务指标查询不抛异常并返回字典结构"""
        from passportd.libs.metrics import _get_business_metrics

        data = _get_business_metrics()
        self.assertIsInstance(data, dict)
        self.assertIn("users_by_status", data)
        self.assertIn("sessions_active", data)
        self.assertIn("auth_by_classify", data)
        self.assertIn("oauth_clients", data)

    def test_process_scan_returns_list(self):
        """进程扫描函数返回列表（非 Linux 环境为空列表）"""
        from passportd.libs.metrics import scan_processes

        procs = scan_processes()
        self.assertIsInstance(procs, list)

    def test_gc_metrics_generated(self):
        """GC 指标（待回收对象数/阈值）可生成"""
        from passportd.libs.metrics import _GCStateCollector

        families = list(_GCStateCollector().collect())
        names = [f.name for f in families]
        self.assertIn("passportd_python_gc_objects_pending", names)
        self.assertIn("passportd_python_gc_threshold", names)
        # 三代均有样本
        pending = [
            f for f in families
            if f.name == "passportd_python_gc_objects_pending"
        ][0]
        self.assertEqual(len(pending.samples), 3)


class GunicornRoleDetectionTest(unittest.TestCase):
    """gunicorn master/worker 角色判定测试"""

    def test_setproctitle_worker_detected_by_ppid(self):
        """comm 被 setproctitle 改为 passportd 时，ppid 是相关进程 → worker"""
        from passportd.libs.metrics import _detect_role

        proc = {
            "comm": "passportd",
            "cmdline": "/usr/bin/gunicorn -w 4 passportd.app:app",
            "ppid": 100,
        }
        self.assertEqual(
            _detect_role(proc, {100, 101, 102}), "gunicorn_worker"
        )

    def test_docker_pid1_master(self):
        """Docker 下 master 为容器 PID 1（ppid=0，无父进程）→ master"""
        from passportd.libs.metrics import _detect_role

        proc = {
            "comm": "passportd",
            "cmdline": (
                "/usr/local/bin/python -m gunicorn -c passportd.py "
                "passportd.app:create_app()"
            ),
            "ppid": 0,
        }
        self.assertEqual(
            _detect_role(proc, {1, 2, 3, 4}), "gunicorn_master"
        )

    def test_docker_worker_ppid_is_pid1_master(self):
        """Docker 下 worker 的 ppid 是容器 PID 1（master）→ worker"""
        from passportd.libs.metrics import _detect_role

        proc = {
            "comm": "passportd",
            "cmdline": (
                "/usr/local/bin/python -m gunicorn -c passportd.py "
                "passportd.app:create_app()"
            ),
            "ppid": 1,
        }
        self.assertEqual(
            _detect_role(proc, {1, 2, 3, 4}), "gunicorn_worker"
        )

    def test_setproctitle_master_detected_by_no_parent(self):
        """comm 被 setproctitle 改为 passportd 时，无 gunicorn 父进程 → master"""
        from passportd.libs.metrics import _detect_role

        proc = {
            "comm": "passportd",
            "cmdline": "/usr/bin/gunicorn -w 4 passportd.app:app",
            "ppid": 1,
        }
        self.assertEqual(
            _detect_role(proc, {100, 101}), "gunicorn_master"
        )

    def test_native_comm_contains_worker(self):
        """未覆盖标题时 comm 含 worker → worker"""
        from passportd.libs.metrics import _detect_role

        proc = {
            "comm": "gunicorn: worker [passportd.app:app]",
            "cmdline": "/usr/bin/gunicorn passportd.app:app",
            "ppid": 1,
        }
        self.assertEqual(_detect_role(proc, {100}), "gunicorn_worker")

    def test_native_comm_contains_master(self):
        """未覆盖标题时 comm 含 master → master"""
        from passportd.libs.metrics import _detect_role

        proc = {
            "comm": "gunicorn: master [passportd.app:app]",
            "cmdline": "/usr/bin/gunicorn passportd.app:app",
            "ppid": 1,
        }
        self.assertEqual(_detect_role(proc, {100}), "gunicorn_master")

    def test_worker_class_in_cmdline_not_confused(self):
        """cmdline 含 --worker-class 不应把 master 误判为 worker"""
        from passportd.libs.metrics import _detect_role

        proc = {
            "comm": "passportd",
            "cmdline": (
                "/usr/bin/gunicorn --worker-class gevent "
                "passportd.app:app"
            ),
            "ppid": 1,
        }
        self.assertEqual(
            _detect_role(proc, {100, 101}), "gunicorn_master"
        )

    def test_unrelated_process_is_app(self):
        """非 gunicorn 进程 → app"""
        from passportd.libs.metrics import _detect_role

        proc = {
            "comm": "python3",
            "cmdline": "python3 worker.py",
            "ppid": 1,
        }
        self.assertEqual(_detect_role(proc, {100}), "app")

    def test_parse_proc_stat_returns_ppid(self):
        """解析 /proc/<pid>/stat 时正确提取 ppid 字段"""
        from passportd.libs.metrics import _parse_proc_stat

        # 第 3 字段(state)=S，第 4 字段(ppid)=1，
        # 后接 utime/stime/starttime/vsize/rss
        stat_line = (
            "123 (gunicorn: master [app]) S 1 123 123 0 -1 4194560 0 0 0 "
            "0 10 5 0 0 20 0 1 0 5555 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 "
            "0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0"
        )
        with patch(
            "passportd.libs.metrics._read_proc", return_value=stat_line
        ):
            data = _parse_proc_stat(123)
        self.assertIsNotNone(data)
        self.assertEqual(data["ppid"], 1)
        self.assertEqual(data["comm"], "gunicorn: master [app]")


class HttpRequestFallbackTest(unittest.TestCase):
    """HTTP 请求计数兜底测试"""

    def test_redis_and_local_empty_outputs_zero_series(self):
        """Redis 与本地均无计数时输出常见 method×status 零值系列，避免 Grafana no data"""
        from passportd.libs.metrics import _HttpRequestCollector

        with patch(
            "passportd.libs.metrics.rdb.hgetall", return_value={}
        ), patch("passportd.libs.metrics._local_req_counter", {}):
            families = list(_HttpRequestCollector().collect())
        family = [
            f for f in families
            if f.name == "passportd_http_requests"
        ][0]
        # 5 个 method × 10 个 status = 50 条零值系列
        self.assertEqual(len(family.samples), 50)
        self.assertEqual(
            family.samples[0].name, "passportd_http_requests_total"
        )
        self.assertEqual(family.samples[0].value, 0.0)

    def test_redis_data_merged_output(self):
        """Redis 有数据时按 method/status 输出计数"""
        from passportd.libs.metrics import _HttpRequestCollector

        with patch(
            "passportd.libs.metrics.rdb.hgetall",
            return_value={"GET:200": "3", "POST:201": "1"},
        ):
            families = list(_HttpRequestCollector().collect())
        family = [
            f for f in families
            if f.name == "passportd_http_requests"
        ][0]
        self.assertEqual(len(family.samples), 2)
        values = {
            (s.labels["method"], s.labels["status"]): s.value
            for s in family.samples
        }
        self.assertEqual(values[("GET", "200")], 3.0)
        self.assertEqual(values[("POST", "201")], 1.0)
