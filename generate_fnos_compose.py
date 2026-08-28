"""Generate a private, ready-to-run fnOS Compose file.

The public ``docker-compose.yml`` deliberately contains non-secret sentinel
tokens.  This helper replaces them with independent cryptographically secure
values without printing any credential to stdout or logs.
"""
from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TEMPLATE_PATH = ROOT / "docker-compose.yml"
OUTPUT_PATH = ROOT / "docker-compose.fnos.yml"

SECRET_TOKENS = {
    "__POSTGRES_ADMIN_PASSWORD__": 32,
    "__POSTGRES_APP_PASSWORD__": 32,
    "__IPTV_AUTH_PASSWORD__": 32,
    "__IPTV_SECRET_KEY__": 48,
}


def _new_secret(entropy_bytes: int) -> str:
    return secrets.token_urlsafe(entropy_bytes)


def generate_fnos_compose(
    output_path: Path | str = OUTPUT_PATH,
    *,
    template_path: Path | str = TEMPLATE_PATH,
    force: bool = False,
    values: dict[str, str] | None = None,
) -> Path:
    """Create one private YAML, refusing to overwrite it by default."""
    template = Path(template_path)
    output = Path(output_path)
    if output.exists() and not force:
        raise FileExistsError(
            f"{output} already exists; keep it for stable credentials or use --force"
        )

    text = template.read_text(encoding="utf-8")
    missing = [token for token in SECRET_TOKENS if token not in text]
    if missing:
        raise RuntimeError(
            "Compose template is missing required secret tokens: "
            + ", ".join(missing)
        )

    replacements = dict(values or {})
    for token, entropy_bytes in SECRET_TOKENS.items():
        replacements.setdefault(token, _new_secret(entropy_bytes))
        value = replacements[token]
        if not isinstance(value, str) or len(value) < 32:
            raise ValueError(f"replacement for {token} must be at least 32 characters")
        text = text.replace(token, value)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, output)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a private single-file fnOS Compose deployment"
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--template", type=Path, default=TEMPLATE_PATH)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output = generate_fnos_compose(
        args.output,
        template_path=args.template,
        force=args.force,
    )
    print(f"Generated private Compose file: {output}")
    print("Back up this file securely; its values were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
