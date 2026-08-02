#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Passportd 1.0 → 2.0 数据迁移脚本

将 MySQL 上的 passportd 1.0 数据迁移到 MySQL 或 PostgreSQL 的 2.0 表结构。

使用方法:
    python tools/migrate_v1_to_v2.py \
        --source mysql://user:pass@host:3306/dbname \
        --target mysql://user:pass@host:3306/dbname

    python tools/migrate_v1_to_v2.py \
        --source mysql://user:pass@host:3306/dbname \
        --target postgresql://user:pass@host:5432/dbname

    # 只做校验不写入
    python tools/migrate_v1_to_v2.py --source ... --target ... --dry-run
"""

import argparse
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# identity_type 映射表
# ---------------------------------------------------------------------------
# 1.0 identity_type → (classify, provider_name)
IDENTITY_MAP = {
    0: None,                     # 保留 → 忽略
    1: ("mobile", None),         # 手机号 → 本地
    2: ("email", None),          # 邮箱 → 本地
    3: ("3rd", "github"),        # GitHub
    4: ("3rd", "qq"),            # QQ
    5: None,                     # 微信 → 忽略
    6: None,                     # 谷歌 → 忽略
    7: ("3rd", "weibo"),         # 新浪微博
    8: None,                     # Coding → 忽略
    9: ("3rd", "gitee"),         # 码云
}

# 被忽略的 identity_type 说明
IGNORE_REASONS = {
    0: "保留类型",
    5: "微信（2.0 不支持）",
    6: "谷歌（2.0 不支持）",
    8: "Coding（2.0 不支持）",
}


def build_target_db(uri: str):
    """根据目标 URI 创建数据库连接。"""
    if uri.startswith("mysql"):
        import pymysql

        from urllib.parse import urlparse

        parsed = urlparse(uri)
        params = {
            "host": parsed.hostname,
            "port": parsed.port or 3306,
            "user": parsed.username,
            "password": parsed.password,
            "database": parsed.path.lstrip("/"),
            "charset": "utf8mb4",
        }
        conn = pymysql.connect(**params)
        return conn, "mysql"
    elif uri.startswith("postgresql") or uri.startswith("postgres"):
        import psycopg

        conn = psycopg.connect(uri)
        return conn, "pgsql"
    else:
        raise ValueError(f"不支持的目标数据库类型: {uri}")


def read_source(uri: str):
    """从源 MySQL 读取 1.0 数据。"""
    import pymysql
    from urllib.parse import urlparse

    parsed = urlparse(uri)
    params = {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": parsed.username,
        "password": parsed.password,
        "database": parsed.path.lstrip("/"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }
    conn = pymysql.connect(**params)
    cur = conn.cursor()

    cur.execute("SELECT * FROM user_profile")
    profiles = cur.fetchall()

    cur.execute("SELECT * FROM user_auth")
    auths = cur.fetchall()

    conn.close()
    return profiles, auths


def parse_third_identifier(identifier: str, identity_type: int) -> str | None:
    """解析第三方 identifier 格式: {identity_type}.{provider_id}

    返回 provider_id，若无法解析或前缀不匹配则返回 None。
    """
    if "." not in identifier:
        return None
    prefix, provider_id = identifier.split(".", 1)
    if prefix != str(identity_type):
        print(
            f"[WARN] identifier 前缀与 identity_type 不匹配: "
            f"identifier={identifier!r}, identity_type={identity_type}"
        )
    return provider_id if provider_id else None


def migrate(
    source_uri: str,
    target_uri: str,
    dry_run: bool = False,
) -> None:
    """执行迁移。"""
    # ---- 读取源数据 ----
    print(f"[INFO] 读取源数据库: {source_uri}")
    profiles, auths = read_source(source_uri)
    print(f"[INFO] 读取到 {len(profiles)} 条 user_profile, {len(auths)} 条 user_auth")

    # ---- 分类 auth 记录 ----
    ignored_auths = []          # 被忽略的 auth 记录
    local_auths_by_uid = defaultdict(list)   # uid → [本地 auth]
    third_auths = []            # 第三方 auth 记录列表

    for a in auths:
        itype = a["identity_type"]
        mapped = IDENTITY_MAP.get(itype)
        if mapped is None:
            ignored_auths.append(a)
            continue
        classify, provider = mapped
        if classify in ("mobile", "email"):
            local_auths_by_uid[a["uid"]].append(a)
        else:
            third_auths.append(a)

    # ---- 构建 2.0 数据 ----
    # passport_user 列表
    users = []
    # uid → (第一个本地 auth 的 certificate) 用于 password_hash
    password_hash_by_uid = {}
    for uid, alist in local_auths_by_uid.items():
        for a in alist:
            if a.get("certificate"):
                password_hash_by_uid[uid] = a["certificate"]
                break

    for profile in profiles:
        uid = profile["uid"]
        user = {
            "uid": uid,
            "nickname": profile.get("nick_name") or "",
            "bio": profile.get("signature") or "",
            "gender": profile.get("gender") or 2,
            "avatar": profile.get("avatar") or "",
            "location": profile.get("location") or "",
            "password_hash": password_hash_by_uid.get(uid),
            "ctime": profile.get("ctime") or 0,
            "mtime": profile.get("mtime") or 0,
            "status": 1,  # 默认启用
            "role": "Admin" if (profile.get("is_admin") or 0) == 1 else "User",
        }
        users.append(user)

    # passport_auth 列表（account 唯一去重，保留第一条）
    new_auths = []
    seen_accounts = set()
    duplicate_count = 0

    def add_auth(auth_dict):
        nonlocal duplicate_count
        account = auth_dict["account"]
        if account in seen_accounts:
            duplicate_count += 1
            print(f"[WARN] 重复 account 已跳过: {account} (uid={auth_dict['uid']})")
            return
        seen_accounts.add(account)
        new_auths.append(auth_dict)

    for uid, alist in local_auths_by_uid.items():
        for a in alist:
            mapped = IDENTITY_MAP.get(a["identity_type"])
            if mapped is None:
                continue
            classify, _ = mapped
            add_auth({
                "uid": uid,
                "account": a["identifier"],
                "tpid": None,
                "classify": classify,
                "ctime": a.get("ctime") or 0,
                "mtime": a.get("mtime") or 0,
            })

    for a in third_auths:
        mapped = IDENTITY_MAP.get(a["identity_type"])
        if mapped is None:
            continue
        classify, provider = mapped
        uid = a["uid"]
        identifier = a["identifier"]
        provider_id = parse_third_identifier(identifier, a["identity_type"])
        if not provider_id:
            ignored_auths.append(a)
            print(f"[WARN] 无法解析第三方 identifier: uid={uid}, identifier={identifier!r}")
            continue
        account = f"{provider}.{provider_id}"
        add_auth({
            "uid": uid,
            "account": account,
            "tpid": None,  # 旧表没有 display_name，2.0 tpid 存的是昵称/登录名
            "classify": classify,
            "ctime": a.get("ctime") or 0,
            "mtime": a.get("mtime") or 0,
        })

    if duplicate_count:
        print(f"[WARN] 共跳过 {duplicate_count} 条重复 account")

    # ---- 输出统计 ----
    print(f"\n[STATS] 迁移统计:")
    print(f"  passport_user: {len(users)} 条")
    print(f"  passport_auth: {len(new_auths)} 条")

    # ---- 打印忽略数据 ----
    if ignored_auths:
        print(f"\n{'='*60}")
        print(f"[IGNORED] 以下 {len(ignored_auths)} 条 user_auth 记录被忽略:")
        print(f"{'='*60}")
        for a in ignored_auths:
            reason = IGNORE_REASONS.get(a["identity_type"], f"不支持的 identity_type={a['identity_type']}")
            print(
                f"  id={a['id']}  uid={a['uid']}  "
                f"identity_type={a['identity_type']}  "
                f"identifier={a['identifier']!r}  "
                f"原因: {reason}"
            )
        print(f"{'='*60}\n")
    else:
        print(f"\n[INFO] 没有被忽略的数据。")

    # ---- Dry run 模式 ----
    if dry_run:
        print("[DRY-RUN] 仅校验模式，不写入目标数据库。")
        print(f"[DRY-RUN] 将写入 {len(users)} 条 User + {len(new_auths)} 条 Auth。")
        return

    # ---- 写入目标数据库 ----
    target_db, db_type = build_target_db(target_uri)
    print(f"[INFO] 目标数据库类型: {db_type}")

    cur = target_db.cursor()
    try:
        if db_type == "mysql":
            _write_mysql(cur, users, new_auths)
        else:
            _write_pgsql(cur, users, new_auths)
        if not dry_run:
            target_db.commit()
            print("[INFO] 迁移完成！")
    except Exception as e:
        target_db.rollback()
        print(f"[ERROR] 写入失败: {e}")
        raise
    finally:
        cur.close()
        target_db.close()


def _write_mysql(cur, users, new_auths):
    """写入 MySQL 目标库。"""
    user_sql = (
        "INSERT INTO passport_user "
        "(uid, nickname, bio, gender, avatar, location, password_hash, ctime, mtime, status, role) "
        "VALUES (%(uid)s, %(nickname)s, %(bio)s, %(gender)s, %(avatar)s, %(location)s, "
        "%(password_hash)s, %(ctime)s, %(mtime)s, %(status)s, %(role)s)"
    )
    auth_sql = (
        "INSERT INTO passport_auth "
        "(uid, account, tpid, classify, ctime, mtime) "
        "VALUES (%(uid)s, %(account)s, %(tpid)s, %(classify)s, %(ctime)s, %(mtime)s)"
    )

    user_count = 0
    for u in users:
        cur.execute(user_sql, u)
        user_count += 1
    print(f"[INFO] 写入 passport_user: {user_count} 条")

    auth_count = 0
    for a in new_auths:
        cur.execute(auth_sql, a)
        auth_count += 1
    print(f"[INFO] 写入 passport_auth: {auth_count} 条")


def _write_pgsql(cur, users, new_auths):
    """写入 PostgreSQL 目标库。"""
    user_cols = [
        "uid", "nickname", "bio", "gender", "avatar", "location",
        "password_hash", "ctime", "mtime", "status", "role",
    ]
    user_placeholders = ", ".join(["%s"] * len(user_cols))
    user_rows = [
        tuple(u[c] for c in user_cols) for u in users
    ]
    cur.executemany(
        f"INSERT INTO passport_user ({', '.join(user_cols)}) VALUES ({user_placeholders})",
        user_rows,
    )
    print(f"[INFO] 写入 passport_user: {len(users)} 条")

    auth_cols = ["uid", "account", "tpid", "classify", "ctime", "mtime"]
    auth_placeholders = ", ".join(["%s"] * len(auth_cols))
    auth_rows = [
        tuple(a[c] for c in auth_cols) for a in new_auths
    ]
    cur.executemany(
        f"INSERT INTO passport_auth ({', '.join(auth_cols)}) VALUES ({auth_placeholders})",
        auth_rows,
    )
    print(f"[INFO] 写入 passport_auth: {len(new_auths)} 条")


def main():
    parser = argparse.ArgumentParser(
        description="Passportd 1.0 → 2.0 数据迁移工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tools/migrate_v1_to_v2.py --source mysql://root:pass@127.0.0.1:3306/old_db --target mysql://root:pass@127.0.0.1:3306/new_db
  python tools/migrate_v1_to_v2.py --source mysql://root:pass@127.0.0.1:3306/old_db --target postgresql://user:pass@127.0.0.1:5432/new_db
  python tools/migrate_v1_to_v2.py --source mysql://root:pass@127.0.0.1:3306/old_db --target mysql://root:pass@127.0.0.1:3306/new_db --dry-run
        """,
    )
    parser.add_argument(
        "--source", required=True,
        help="源数据库 URI (仅支持 MySQL)，格式: mysql://user:pass@host:port/dbname",
    )
    parser.add_argument(
        "--target", required=True,
        help="目标数据库 URI，支持 MySQL 和 PostgreSQL，格式: mysql://... 或 postgresql://...",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅校验不写入，打印迁移数据概览",
    )
    args = parser.parse_args()

    if not args.source.startswith("mysql"):
        print("[ERROR] 源数据库仅支持 MySQL", file=sys.stderr)
        sys.exit(1)

    migrate(args.source, args.target, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
