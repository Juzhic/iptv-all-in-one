import os
import uuid
from pathlib import Path

import pytest

import generate_fnos_compose as generator


@pytest.fixture
def local_compose_dir():
    path = Path(__file__).resolve().parents[1] / "output" / f".compose-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        for child in path.iterdir():
            child.unlink()
        path.rmdir()


def _template_text():
    return "\n".join(generator.SECRET_TOKENS) + "\n"


def _strong_values():
    return {
        token: f"secret-{index}-" + "x" * 40
        for index, token in enumerate(generator.SECRET_TOKENS)
    }


def test_generator_replaces_every_secret_without_printing_it(local_compose_dir, capsys):
    template = local_compose_dir / "template.yml"
    output = local_compose_dir / "docker-compose.fnos.yml"
    template.write_text(_template_text(), encoding="utf-8")
    values = _strong_values()

    generated = generator.generate_fnos_compose(
        output, template_path=template, values=values
    )

    content = generated.read_text(encoding="utf-8")
    assert all(token not in content for token in generator.SECRET_TOKENS)
    assert all(value in content for value in values.values())
    assert capsys.readouterr().out == ""
    if os.name != "nt":
        assert generated.stat().st_mode & 0o777 == 0o600


def test_generator_refuses_to_replace_stable_private_file(local_compose_dir):
    template = local_compose_dir / "template.yml"
    output = local_compose_dir / "private.yml"
    template.write_text(_template_text(), encoding="utf-8")
    output.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        generator.generate_fnos_compose(output, template_path=template)

    assert output.read_text(encoding="utf-8") == "keep"


def test_generator_force_rotates_all_values(local_compose_dir):
    template = local_compose_dir / "template.yml"
    output = local_compose_dir / "private.yml"
    template.write_text(_template_text(), encoding="utf-8")

    generator.generate_fnos_compose(output, template_path=template)
    first = output.read_text(encoding="utf-8")
    generator.generate_fnos_compose(output, template_path=template, force=True)
    second = output.read_text(encoding="utf-8")

    assert first != second
    assert all(token not in second for token in generator.SECRET_TOKENS)


def test_generator_rejects_incomplete_template(local_compose_dir):
    template = local_compose_dir / "template.yml"
    template.write_text("__POSTGRES_ADMIN_PASSWORD__\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing required secret tokens"):
        generator.generate_fnos_compose(
            local_compose_dir / "private.yml", template_path=template
        )


def test_generator_rejects_weak_override(local_compose_dir):
    template = local_compose_dir / "template.yml"
    template.write_text(_template_text(), encoding="utf-8")
    values = _strong_values()
    values["__IPTV_AUTH_PASSWORD__"] = "short"

    with pytest.raises(ValueError, match="at least 32 characters"):
        generator.generate_fnos_compose(
            local_compose_dir / "private.yml",
            template_path=template,
            values=values,
        )


def test_private_compose_and_mysql_dump_are_excluded_from_git_and_build_context():
    root = Path(__file__).resolve().parents[1]
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (root / ".dockerignore").read_text(encoding="utf-8")

    for ignored in ("/docker-compose.fnos.yml", "/iptv_backup.sql"):
        assert ignored in gitignore
        assert ignored in dockerignore
