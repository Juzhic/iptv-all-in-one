"""Generate a .env file with a random database password."""
from __future__ import annotations

import argparse
import re
import secrets
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"
PASSWORD_PATTERN = re.compile(r"^DB_PASSWORD=.*$", re.MULTILINE)


def _read_existing_password(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("DB_PASSWORD="):
            return line.split("=", 1)[1].strip()
    return ""


def generate_env(force: bool = False) -> str:
    if not EXAMPLE_PATH.exists():
        raise FileNotFoundError(f"Missing template: {EXAMPLE_PATH}")

    if ENV_PATH.exists() and not force:
        existing = ENV_PATH.read_text(encoding="utf-8")
        if _read_existing_password(existing):
            raise RuntimeError(".env already exists with DB_PASSWORD; use --force to regenerate it")
        template = existing
    else:
        template = EXAMPLE_PATH.read_text(encoding="utf-8")

    password = secrets.token_urlsafe(32)
    if PASSWORD_PATTERN.search(template):
        output = PASSWORD_PATTERN.sub(f"DB_PASSWORD={password}", template, count=1)
    else:
        output = template.rstrip() + f"\nDB_PASSWORD={password}\n"

    ENV_PATH.write_text(output, encoding="utf-8", newline="\n")
    return password


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate .env with a random DB_PASSWORD.")
    parser.add_argument("--force", action="store_true", help="overwrite an existing DB_PASSWORD")
    args = parser.parse_args()

    generate_env(force=args.force)
    print(f"Generated {ENV_PATH}")
    print("DB_PASSWORD has been written to .env.")


if __name__ == "__main__":
    main()
