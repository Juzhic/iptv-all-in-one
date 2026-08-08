"""One-time 1.x -> 2.0 database/security migration.

This command is intentionally the only application-side path that receives the
MySQL root password.  It creates the dedicated account, verifies it, and then
loads scanner configuration through the encryption migration.  A newly-created
account is dropped again if any later step fails.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import pymysql

from generate_env import _parse_values


ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = ROOT / ".env"
_ACCOUNT_COMPONENT = re.compile(r"^[A-Za-z0-9_.:%-]{1,255}$")


def _load_environment(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}; run python generate_env.py --upgrade first"
        )
    values = _parse_values(path.read_text(encoding="utf-8-sig"))
    for key, value in values.items():
        os.environ.setdefault(key, value)


def _require_strong(name: str, minimum: int) -> str:
    value = os.environ.get(name, "")
    if len(value) < minimum or value != value.strip() or len(set(value)) < 4:
        raise ValueError(f"{name} must be a strong value of at least {minimum} characters")
    return value


def _account_sql(connection, username: str, host: str) -> str:
    if not _ACCOUNT_COMPONENT.fullmatch(username) or username.casefold() == "root":
        raise ValueError("DB_USER must be a dedicated non-root MySQL account")
    if not _ACCOUNT_COMPONENT.fullmatch(host):
        raise ValueError("DB_USER_HOST contains unsupported characters")
    return f"{connection.escape(username)}@{connection.escape(host)}"


def _database_sql(name: str) -> str:
    if not name or len(name) > 64 or "\x00" in name:
        raise ValueError("DB_NAME is invalid")
    return "`" + name.replace("`", "``") + "`"


def migrate(env_path: Path = DEFAULT_ENV_PATH) -> None:
    _load_environment(env_path)
    # The legacy root password must be used exactly as-is to reach an existing
    # MySQL volume. It may predate the v2 strength policy; the long-lived app
    # never receives it after migration.
    root_password = os.environ.get("MYSQL_ROOT_PASSWORD", "")
    if not root_password:
        raise ValueError("MYSQL_ROOT_PASSWORD is required for the one-time migration")
    app_password = _require_strong("DB_PASSWORD", 16)
    _require_strong("IPTV_AUTH_PASSWORD", 16)
    _require_strong("IPTV_SECRET_KEY", 32)
    if root_password == app_password:
        raise ValueError("MYSQL_ROOT_PASSWORD and DB_PASSWORD must differ")

    db_host = os.environ.get("DB_HOST", "mysql")
    db_port = int(os.environ.get("DB_PORT", "3306"))
    db_name = os.environ.get("DB_NAME", "iptv-all-in-one")
    db_charset = os.environ.get("DB_CHARSET", "utf8mb4")
    app_user = os.environ.get("DB_USER", "iptv_app")
    app_user_host = os.environ.get("DB_USER_HOST", "%")

    root_connection = None
    created_user = False
    account = ""
    try:
        root_connection = pymysql.connect(
            host=db_host,
            port=db_port,
            user="root",
            password=root_password,
            charset=db_charset,
            autocommit=True,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )
        account = _account_sql(root_connection, app_user, app_user_host)
        database_identifier = _database_sql(db_name)

        with root_connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = %s",
                (db_name,),
            )
            if cursor.fetchone() is None:
                raise RuntimeError(f"Database {db_name!r} does not exist")

            cursor.execute(
                "SELECT 1 FROM mysql.user WHERE User = %s AND Host = %s",
                (app_user, app_user_host),
            )
            user_exists = cursor.fetchone() is not None
            if not user_exists:
                cursor.execute(f"CREATE USER {account} IDENTIFIED BY %s", (app_password,))
                created_user = True
                cursor.execute(
                    f"GRANT ALL PRIVILEGES ON {database_identifier}.* TO {account}"
                )

        # Verify the persistent service can authenticate without the root secret
        # before touching scanner configuration.
        app_connection = pymysql.connect(
            host=db_host,
            port=db_port,
            user=app_user,
            password=app_password,
            database=db_name,
            charset=db_charset,
            autocommit=True,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )
        app_connection.close()

        # Import only after environment setup so database and encryption modules
        # bind to the dedicated account and the persistent application secret.
        import database.db as database_db
        from scanner_integration.config_bridge import get_scan_config

        database_db._db_config = None
        database_db._reset_thread_conn()
        get_scan_config()
        database_db._reset_thread_conn()
    except BaseException:
        if created_user and root_connection is not None and account:
            try:
                with root_connection.cursor() as cursor:
                    cursor.execute(f"DROP USER IF EXISTS {account}")
            except Exception as cleanup_error:
                print(
                    f"Rollback warning: failed to remove the new app user: {cleanup_error}",
                    file=sys.stderr,
                )
        raise
    finally:
        if root_connection is not None:
            root_connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the v2 app DB user and encrypt legacy scanner API keys."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_PATH,
        help="deployment env file (default: repository .env)",
    )
    args = parser.parse_args()
    try:
        migrate(args.env_file.resolve())
    except Exception as exc:
        print(f"2.0 migration failed: {exc}", file=sys.stderr)
        return 1
    print("2.0 migration completed: dedicated DB user verified and API keys secured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
