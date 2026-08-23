# -*- coding: utf-8 -*-
"""数据库连接字符集（utf8mb4）处理测试。

范围：
- MySQL/MariaDB 连接串未指定 charset 时自动追加 charset=utf8mb4
- 已指定 charset（含 utf8mb4）时保持原样
- 已有其他 query 参数时以 & 拼接，不破坏原参数
- SQLite / PostgreSQL 不受影响
"""

import unittest

from passportd.models.model import _ensure_mysql_charset


class TestEnsureMySQLCharset(unittest.TestCase):
    def test_mysql_no_query_appends_charset(self):
        uri = "mysql+pool://user:pwd@localhost:3306/passport"
        self.assertEqual(_ensure_mysql_charset(uri), uri + "?charset=utf8mb4")

    def test_mysql_existing_query_keeps_params(self):
        uri = "mysql+pool://user:pwd@localhost:3306/passport?max_connections=20"
        self.assertEqual(_ensure_mysql_charset(uri), uri + "&charset=utf8mb4")

    def test_mysql_existing_charset_untouched(self):
        for uri in (
            "mysql+pool://user:pwd@localhost:3306/passport?charset=utf8",
            "mysql+pool://user:pwd@localhost:3306/passport?charset=utf8mb4&max_connections=20",
        ):
            self.assertEqual(_ensure_mysql_charset(uri), uri)

    def test_sqlite_untouched(self):
        uri = "sqlite:///tmp/passport.db"
        self.assertEqual(_ensure_mysql_charset(uri), uri)

    def test_postgresql_untouched(self):
        uri = "psycopg3+pool://user:pwd@localhost:5432/passport"
        self.assertEqual(_ensure_mysql_charset(uri), uri)


if __name__ == "__main__":
    unittest.main()
