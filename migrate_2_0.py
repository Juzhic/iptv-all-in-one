"""Legacy one-time 1.x -> 2.0 database/security migration.

This historical helper is excluded from the PostgreSQL 3.0 runtime image.

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


def _load_environment(path: Path, *, environment_only: bool = False) -> None:
    """Load a host env file or validate the read-only Docker env contract."""
    if path.exists() and not environment_only:
        values = _parse_values(path.read_text(encoding="utf-8-sig"))
        for key, value in values.items():
            os.environ.setdefault(key, value)
        return

    base_required = (
        "MYSQL_ROOT_PASSWORD",
        "IPTV_AUTH_PASSWORD",
        "IPTV_SECRET_KEY",
    )
    migration_pair = (
        os.environ.get("IPTV_MIGRATION_DB_USER", "").strip(),
        os.environ.get("IPTV_MIGRATION_DB_PASSWORD", ""),
    )
    active_pair = (
        os.environ.get("DB_USER", "").strip(),
        os.environ.get("DB_PASSWORD", ""),
    )
    has_base = all(os.environ.get(name) for name in base_required)
    has_account = all(migration_pair) if environment_only else (
        all(migration_pair) or all(active_pair)
    )
    if has_base and has_account:
        return

    if environment_only:
        raise ValueError(
            "Environment-only migration requires MYSQL_ROOT_PASSWORD, "
            "IPTV_AUTH_PASSWORD, IPTV_SECRET_KEY and both "
            "IPTV_MIGRATION_DB_* values"
        )
    raise FileNotFoundError(
        f"Missing {path} and required environment values; "
        "run python generate_env.py --upgrade first"
    )


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


def _application_credentials() -> tuple[str, str]:
    """Resolve a staged upgrade account, or an already dedicated account."""
    migration_user = os.environ.get("IPTV_MIGRATION_DB_USER", "").strip()
    migration_password = os.environ.get("IPTV_MIGRATION_DB_PASSWORD", "")
    if bool(migration_user) != bool(migration_password):
        raise ValueError(
            "IPTV_MIGRATION_DB_USER and IPTV_MIGRATION_DB_PASSWORD must be set together"
        )
    if migration_user:
        return migration_user, migration_password
    return os.environ.get("DB_USER", "").strip(), os.environ.get("DB_PASSWORD", "")


def _restore_environment(name: str, original: str | None) -> None:
    if original is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = original


def migrate(
    env_path: Path = DEFAULT_ENV_PATH,
    *,
    environment_only: bool = False,
) -> None:
    _load_environment(env_path, environment_only=environment_only)
    # The legacy root password must be used exactly as-is to reach an existing
    # MySQL volume. It may predate the v2 strength policy; the long-lived app
    # never receives it after migration.
    root_password = os.environ.get("MYSQL_ROOT_PASSWORD", "")
    if not root_password:
        raise ValueError("MYSQL_ROOT_PASSWORD is required for the one-time migration")
    app_user, app_password = _application_credentials()
    if len(app_password) < 16 or app_password != app_password.strip() or len(set(app_password)) < 4:
        raise ValueError("application DB password must be a strong value of at least 16 characters")
    _require_strong("IPTV_AUTH_PASSWORD", 16)
    _require_strong("IPTV_SECRET_KEY", 32)
    if root_password == app_password:
        raise ValueError("MYSQL_ROOT_PASSWORD and DB_PASSWORD must differ")

    db_host = os.environ.get("DB_HOST", "mysql")
    db_port = int(os.environ.get("DB_PORT", "3306"))
    db_name = os.environ.get("DB_NAME", "iptv-all-in-one")
    db_charset = os.environ.get("DB_CHARSET", "utf8mb4")
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
            else:
                # Never take over or rotate an account that may have been
                # provisioned by an operator. Authenticate first, without
                # selecting the application database (it may not be granted
                # yet), and only grant after the staged credentials match.
                existing_connection = None
                try:
                    existing_connection = pymysql.connect(
                        host=db_host,
                        port=db_port,
                        user=app_user,
                        password=app_password,
                        charset=db_charset,
                        autocommit=True,
                        connect_timeout=10,
                        read_timeout=30,
                        write_timeout=30,
                    )
                except pymysql.err.OperationalError as exc:
                    error_code = exc.args[0] if exc.args else None
                    if error_code == 1045:
                        raise RuntimeError(
                            "The dedicated MySQL account already exists but its "
                            "credentials do not match the staged password; refusing "
                            "to alter the existing account"
                        ) from exc
                    raise
                finally:
                    if existing_connection is not None:
                        existing_connection.close()
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
        original_db_user = os.environ.get("DB_USER")
        original_db_password = os.environ.get("DB_PASSWORD")
        database_db = None
        previous_db_config = None
        try:
            os.environ["DB_USER"] = app_user
            os.environ["DB_PASSWORD"] = app_password
            import database.db as database_db
            from scanner_integration import config_bridge

            previous_db_config = database_db._db_config
            database_db._db_config = None
            database_db._reset_thread_conn()
            database_db.init_db()
            config_bridge.migrate_stored_api_keys()
        finally:
            if database_db is not None:
                database_db._reset_thread_conn()
                database_db._db_config = previous_db_config
            _restore_environment("DB_USER", original_db_user)
            _restore_environment("DB_PASSWORD", original_db_password)
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
    parser.add_argument(
        "--environment-only",
        action="store_true",
        help=(
            "read all values from the process environment without opening or "
            "writing an env file (used by the read-only Compose migration service)"
        ),
    )
    args = parser.parse_args()
    try:
        migrate(
            args.env_file.resolve(),
            environment_only=args.environment_only,
        )
    except Exception as exc:
        print(f"2.0 migration failed: {exc}", file=sys.stderr)
        return 1
    print("2.0 migration completed: dedicated DB user verified and API keys secured.")
    print("Now run python generate_env.py --finalize-upgrade before starting the app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
