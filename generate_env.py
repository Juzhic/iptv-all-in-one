"""Create an atomic .env file with stable, independent strong credentials."""
from __future__ import annotations

import argparse
import os
import re
import secrets
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"
_ROTATABLE_CREDENTIAL_KEYS = (
    "MYSQL_ROOT_PASSWORD",
    "DB_PASSWORD",
    "IPTV_AUTH_PASSWORD",
)


def _parse_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _replace_or_append(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=).*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda match: f"{match.group(1)}{value}", text, count=1)
    return text.rstrip() + f"\n{key}={value}\n"


def _new_secret(byte_count: int = 32) -> str:
    return secrets.token_urlsafe(byte_count)


def _is_strong_secret(value: str, minimum: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) >= minimum
        and value == value.strip()
        and len(set(value)) >= 4
    )


def _validate_account_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.:%-]{1,255}", name)) and (
        name.casefold() != "root"
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text.rstrip() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def generate_env_values(
    force: bool = False,
    upgrade: bool = False,
) -> dict[str, str]:
    """Fill missing secrets while preserving existing values and settings.

    ``--upgrade`` converts the legacy root-only layout without changing the
    password that the existing MySQL root account actually uses. ``--force``
    may rotate DB/Auth credentials, but deliberately never rotates an existing
    IPTV_SECRET_KEY because doing so would orphan encrypted scanner API keys.
    """
    if force and upgrade:
        raise ValueError("force and upgrade are mutually exclusive")
    if not EXAMPLE_PATH.exists():
        raise FileNotFoundError(f"Missing template: {EXAMPLE_PATH}")

    env_exists = ENV_PATH.exists()
    if env_exists:
        text = ENV_PATH.read_text(encoding="utf-8-sig")
    else:
        text = EXAMPLE_PATH.read_text(encoding="utf-8-sig")
    values = _parse_values(text)

    db_user = values.get("DB_USER", "").strip()
    existing_db_password = values.get("DB_PASSWORD", "")
    fresh_install = not env_exists or not existing_db_password
    legacy_root_only = (
        env_exists
        and bool(existing_db_password)
        and (not db_user or db_user.casefold() == "root")
    )
    pending_user = values.get("IPTV_MIGRATION_DB_USER", "").strip()
    pending_password = values.get("IPTV_MIGRATION_DB_PASSWORD", "")
    staged_upgrade = legacy_root_only and bool(pending_user and pending_password)
    if legacy_root_only and not upgrade and not staged_upgrade:
        # Pulling a new checkout must not make the historical one-argument
        # generator destructive. Treat a plain invocation as a compatibility
        # no-op when the legacy password is already usable; the explicit
        # --upgrade path below stages all new 2.0 values.
        if not force:
            return values
        raise RuntimeError(
            "Legacy root-only .env detected; use --upgrade instead of --force "
            "so the existing root password remains usable"
        )
    if legacy_root_only:
        # Stage the new account without changing the active 1.x connection.
        # migrate_2_0.py switches DB_USER/DB_PASSWORD only after verification.
        values["MYSQL_ROOT_PASSWORD"] = existing_db_password
        text = _replace_or_append(
            text, "MYSQL_ROOT_PASSWORD", existing_db_password
        )
        values["IPTV_MIGRATION_DB_USER"] = pending_user or "iptv_app"
        text = _replace_or_append(
            text, "IPTV_MIGRATION_DB_USER", values["IPTV_MIGRATION_DB_USER"]
        )
        values["IPTV_MIGRATION_DB_PASSWORD"] = pending_password or _new_secret()
        text = _replace_or_append(
            text,
            "IPTV_MIGRATION_DB_PASSWORD",
            values["IPTV_MIGRATION_DB_PASSWORD"],
        )
        values["IPTV_REQUIRE_STRONG_CREDENTIALS"] = "0"
        text = _replace_or_append(text, "IPTV_REQUIRE_STRONG_CREDENTIALS", "0")
        values["IPTV_CONTAINER_USER"] = "root"
        text = _replace_or_append(text, "IPTV_CONTAINER_USER", "root")
        values["IPTV_HARDENED_CONTAINER"] = "false"
        text = _replace_or_append(text, "IPTV_HARDENED_CONTAINER", "false")

    if (not db_user or db_user.casefold() == "root") and not legacy_root_only:
        values["DB_USER"] = "iptv_app"
        text = _replace_or_append(text, "DB_USER", values["DB_USER"])

    if not values.get("MYSQL_INIT_USER", "").strip():
        values["MYSQL_INIT_USER"] = "iptv_app"
        text = _replace_or_append(text, "MYSQL_INIT_USER", values["MYSQL_INIT_USER"])

    if not values.get("IPTV_AUTH_USERNAME", "").strip():
        values["IPTV_AUTH_USERNAME"] = "admin"
        text = _replace_or_append(
            text, "IPTV_AUTH_USERNAME", values["IPTV_AUTH_USERNAME"]
        )

    credential_keys = _ROTATABLE_CREDENTIAL_KEYS
    if legacy_root_only:
        credential_keys = ("IPTV_AUTH_PASSWORD",)
    for key in credential_keys:
        current = values.get(key, "")
        if force or not current:
            current = _new_secret()
            values[key] = current
            text = _replace_or_append(text, key, current)

    init_password = values.get("IPTV_MIGRATION_DB_PASSWORD") or values["DB_PASSWORD"]
    values["MYSQL_INIT_PASSWORD"] = init_password
    text = _replace_or_append(text, "MYSQL_INIT_PASSWORD", values["MYSQL_INIT_PASSWORD"])

    if not legacy_root_only:
        # A fresh or already-migrated env can fail closed immediately.
        values["IPTV_REQUIRE_STRONG_CREDENTIALS"] = "1"
        text = _replace_or_append(text, "IPTV_REQUIRE_STRONG_CREDENTIALS", "1")
        if fresh_install:
            values["IPTV_CONTAINER_USER"] = "10001:10001"
            values["IPTV_HARDENED_CONTAINER"] = "true"
        else:
            # Existing dedicated-account deployments may still use old
            # root-owned volumes. Preserve an operator's explicit choice and
            # default missing runtime flags to compatibility, not breakage.
            values.setdefault("IPTV_CONTAINER_USER", "root")
            values.setdefault("IPTV_HARDENED_CONTAINER", "false")
        text = _replace_or_append(
            text, "IPTV_CONTAINER_USER", values["IPTV_CONTAINER_USER"]
        )
        text = _replace_or_append(
            text,
            "IPTV_HARDENED_CONTAINER",
            values["IPTV_HARDENED_CONTAINER"],
        )

    # Never rotate this key implicitly, including under --force.
    if not values.get("IPTV_SECRET_KEY", ""):
        values["IPTV_SECRET_KEY"] = _new_secret(48)
        text = _replace_or_append(
            text, "IPTV_SECRET_KEY", values["IPTV_SECRET_KEY"]
        )

    if not legacy_root_only and values["MYSQL_ROOT_PASSWORD"] == values["DB_PASSWORD"]:
        if not force:
            raise RuntimeError(
                "MYSQL_ROOT_PASSWORD and DB_PASSWORD must differ; use --force "
                "to regenerate credentials"
            )
        while values["MYSQL_ROOT_PASSWORD"] == values["DB_PASSWORD"]:
            values["MYSQL_ROOT_PASSWORD"] = _new_secret()
        text = _replace_or_append(
            text, "MYSQL_ROOT_PASSWORD", values["MYSQL_ROOT_PASSWORD"]
        )

    _atomic_write(ENV_PATH, text)
    return values


def finalize_upgrade() -> dict[str, str]:
    """Activate a verified staged DB account without rotating any secret."""
    if not ENV_PATH.exists():
        raise FileNotFoundError(f"Missing {ENV_PATH}; run --upgrade first")
    text = ENV_PATH.read_text(encoding="utf-8-sig")
    values = _parse_values(text)
    app_user = values.get("IPTV_MIGRATION_DB_USER", "").strip()
    app_password = values.get("IPTV_MIGRATION_DB_PASSWORD", "")
    if (
        not _validate_account_name(app_user)
        or len(app_password) < 16
        or app_password != app_password.strip()
        or len(set(app_password)) < 4
    ):
        raise RuntimeError(
            "No staged application account found; run --upgrade and the "
            "migrate-2-0 service successfully before --finalize-upgrade"
        )
    required_strong = (
        ("IPTV_AUTH_PASSWORD", 16),
        ("IPTV_SECRET_KEY", 32),
    )
    missing_or_weak = [
        name for name, minimum in required_strong
        if not _is_strong_secret(values.get(name, ""), minimum)
    ]
    if missing_or_weak:
        raise RuntimeError(
            "Cannot enable strict mode; missing or weak staged credentials: "
            + ", ".join(missing_or_weak)
        )
    root_password = values.get("MYSQL_ROOT_PASSWORD", "")
    if root_password and root_password == app_password:
        raise RuntimeError(
            "Cannot enable strict mode because MYSQL_ROOT_PASSWORD and the "
            "staged application password are identical"
        )
    text = _replace_or_append(text, "DB_USER", app_user)
    text = _replace_or_append(text, "DB_PASSWORD", app_password)
    text = _replace_or_append(text, "MYSQL_INIT_USER", app_user)
    text = _replace_or_append(text, "MYSQL_INIT_PASSWORD", app_password)
    text = _replace_or_append(text, "IPTV_MIGRATION_DB_USER", "")
    text = _replace_or_append(text, "IPTV_MIGRATION_DB_PASSWORD", "")
    text = _replace_or_append(text, "IPTV_REQUIRE_STRONG_CREDENTIALS", "1")
    # Do not switch the container user automatically. Existing 1.x bind mounts
    # or named volumes may still be root-owned; changing the database account
    # must not make output/data unwritable in the same step.
    _atomic_write(ENV_PATH, text)
    return _parse_values(text)


def recover_interrupted_early_upgrade() -> dict[str, str]:
    """Restore the reversible staging layout used by fixed 2.0 upgrades.

    The first 2.0 generator changed active DB_USER/DB_PASSWORD before the
    dedicated MySQL account was proven to exist. Its output is recoverable
    when MYSQL_ROOT_PASSWORD still contains the old 1.x root password: stage
    the premature app pair, then reactivate root until migrate/finalize runs.
    """
    if not ENV_PATH.exists():
        raise FileNotFoundError(f"Missing {ENV_PATH}; restore the 1.x backup first")
    text = ENV_PATH.read_text(encoding="utf-8-sig")
    values = _parse_values(text)
    app_user = values.get("DB_USER", "").strip()
    app_password = values.get("DB_PASSWORD", "")
    root_password = values.get("MYSQL_ROOT_PASSWORD", "")
    if (
        not _validate_account_name(app_user)
        or not _is_strong_secret(app_password, 16)
        or not root_password
        or root_password == app_password
    ):
        raise RuntimeError(
            "Cannot recognize a recoverable early-2.0 upgrade; restore the "
            "pre-upgrade .env backup instead"
        )
    pending_user = values.get("IPTV_MIGRATION_DB_USER", "").strip()
    pending_password = values.get("IPTV_MIGRATION_DB_PASSWORD", "")
    if (pending_user or pending_password) and (
        pending_user != app_user or pending_password != app_password
    ):
        raise RuntimeError(
            "Different staged credentials already exist; refusing to overwrite them"
        )

    text = _replace_or_append(text, "IPTV_MIGRATION_DB_USER", app_user)
    text = _replace_or_append(text, "IPTV_MIGRATION_DB_PASSWORD", app_password)
    text = _replace_or_append(text, "MYSQL_INIT_USER", app_user)
    text = _replace_or_append(text, "MYSQL_INIT_PASSWORD", app_password)
    text = _replace_or_append(text, "DB_USER", "root")
    text = _replace_or_append(text, "DB_PASSWORD", root_password)
    text = _replace_or_append(text, "IPTV_REQUIRE_STRONG_CREDENTIALS", "0")
    text = _replace_or_append(text, "IPTV_CONTAINER_USER", "root")
    text = _replace_or_append(text, "IPTV_HARDENED_CONTAINER", "false")
    _atomic_write(ENV_PATH, text)
    return _parse_values(text)


def enable_container_hardening() -> dict[str, str]:
    """Opt into the non-root/read-only runtime after volume ownership checks."""
    if not ENV_PATH.exists():
        raise FileNotFoundError(f"Missing {ENV_PATH}; generate deployment credentials first")
    text = ENV_PATH.read_text(encoding="utf-8-sig")
    values = _parse_values(text)
    db_user = values.get("DB_USER", "").strip()
    if not _validate_account_name(db_user):
        raise RuntimeError(
            "Container hardening requires an active dedicated non-root DB_USER"
        )
    required_strong = (
        ("DB_PASSWORD", 16),
        ("IPTV_AUTH_PASSWORD", 16),
        ("IPTV_SECRET_KEY", 32),
    )
    missing_or_weak = [
        name for name, minimum in required_strong
        if not _is_strong_secret(values.get(name, ""), minimum)
    ]
    if missing_or_weak:
        raise RuntimeError(
            "Cannot harden container with missing or weak credentials: "
            + ", ".join(missing_or_weak)
        )
    text = _replace_or_append(text, "IPTV_CONTAINER_USER", "10001:10001")
    text = _replace_or_append(text, "IPTV_HARDENED_CONTAINER", "true")
    text = _replace_or_append(text, "IPTV_REQUIRE_STRONG_CREDENTIALS", "1")
    _atomic_write(ENV_PATH, text)
    return _parse_values(text)


def generate_env(force: bool = False, upgrade: bool = False) -> str:
    """Backward-compatible helper returning the application DB password."""
    return generate_env_values(force=force, upgrade=upgrade)["DB_PASSWORD"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate .env with independent strong deployment secrets."
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--force",
        action="store_true",
        help=(
            "regenerate DB/Auth credentials while preserving settings and any "
            "existing IPTV_SECRET_KEY"
        ),
    )
    modes.add_argument(
        "--upgrade",
        action="store_true",
        help=(
            "upgrade a legacy root-only .env, preserving its DB_PASSWORD as "
            "MYSQL_ROOT_PASSWORD and generating a dedicated app password"
        ),
    )
    modes.add_argument(
        "--finalize-upgrade",
        action="store_true",
        help=(
            "activate the staged application DB account after migrate-2-0 "
            "completed successfully"
        ),
    )
    modes.add_argument(
        "--recover-interrupted-upgrade",
        action="store_true",
        help=(
            "recover an .env modified by the original 2.0 --upgrade before "
            "the dedicated database account was created"
        ),
    )
    modes.add_argument(
        "--enable-container-hardening",
        action="store_true",
        help=(
            "opt into UID 10001 and a read-only root filesystem after data "
            "and output volume ownership has been verified"
        ),
    )
    args = parser.parse_args()

    if args.finalize_upgrade:
        finalize_upgrade()
    elif args.recover_interrupted_upgrade:
        recover_interrupted_early_upgrade()
    elif args.enable_container_hardening:
        enable_container_hardening()
    else:
        generate_env(force=args.force, upgrade=args.upgrade)
    print(f"Generated {ENV_PATH} atomically.")
    print("Deployment credentials were written without printing their values.")
    if args.upgrade:
        print("Active 1.x DB credentials were preserved for rollback.")
        print("Next, run migrate-2-0; only then run --finalize-upgrade.")
    if args.finalize_upgrade:
        print("The verified application DB account is now active and strict mode is enabled.")
    if args.recover_interrupted_upgrade:
        print("Interrupted early-2.0 credentials were restored to staged migration mode.")
        print("Next, run migrate-2-0; only then run --finalize-upgrade.")
    if args.enable_container_hardening:
        print("Container hardening is enabled; rebuild the application container.")


if __name__ == "__main__":
    main()
