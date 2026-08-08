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
    legacy_root_only = (
        env_exists
        and bool(existing_db_password)
        and (not db_user or db_user.casefold() == "root")
    )
    if legacy_root_only and not upgrade:
        raise RuntimeError(
            "Legacy root-only .env detected; run generate_env.py --upgrade "
            "so the existing root password is preserved safely"
        )
    if legacy_root_only:
        # docker-compose 1.x used DB_PASSWORD as MYSQL_ROOT_PASSWORD. Preserve
        # that exact value for the already-initialized MySQL volume, then issue
        # a distinct new password for the dedicated application account.
        values["MYSQL_ROOT_PASSWORD"] = existing_db_password
        text = _replace_or_append(
            text, "MYSQL_ROOT_PASSWORD", existing_db_password
        )
        values["DB_PASSWORD"] = _new_secret()
        text = _replace_or_append(text, "DB_PASSWORD", values["DB_PASSWORD"])

    if not db_user or db_user.casefold() == "root":
        values["DB_USER"] = "iptv_app"
        text = _replace_or_append(text, "DB_USER", values["DB_USER"])

    if not values.get("IPTV_AUTH_USERNAME", "").strip():
        values["IPTV_AUTH_USERNAME"] = "admin"
        text = _replace_or_append(
            text, "IPTV_AUTH_USERNAME", values["IPTV_AUTH_USERNAME"]
        )

    for key in _ROTATABLE_CREDENTIAL_KEYS:
        current = values.get(key, "")
        if force or not current:
            current = _new_secret()
            values[key] = current
            text = _replace_or_append(text, key, current)

    # Never rotate this key implicitly, including under --force.
    if not values.get("IPTV_SECRET_KEY", ""):
        values["IPTV_SECRET_KEY"] = _new_secret(48)
        text = _replace_or_append(
            text, "IPTV_SECRET_KEY", values["IPTV_SECRET_KEY"]
        )

    if values["MYSQL_ROOT_PASSWORD"] == values["DB_PASSWORD"]:
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
    args = parser.parse_args()

    generate_env(force=args.force, upgrade=args.upgrade)
    print(f"Generated {ENV_PATH} atomically.")
    print("Deployment credentials were written without printing their values.")
    if args.upgrade:
        print("Next, run the one-time migrate_2_0.py command to create the app user and encrypt legacy API keys.")


if __name__ == "__main__":
    main()
