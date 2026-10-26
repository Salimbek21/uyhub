"""The CLI exposes exactly the entrypoints the Docker image and operators rely on."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from uyhub import __version__
from uyhub.cli import SERVICE_NAMES, app

pytestmark = pytest.mark.unit

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_help_lists_every_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "200")  # stop rich from wrapping command names
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for service in SERVICE_NAMES:
        assert service in result.stdout, f"{service} missing from `uyhub --help`"


def test_service_names_match_the_spec() -> None:
    """SPEC section 2.1 defines these seven services; miniapp is not a CLI command."""
    assert set(SERVICE_NAMES) == {
        "collector",
        "parser",
        "api",
        "bot",
        "poster",
        "scheduler",
    }


@pytest.mark.parametrize("command", ["check", "init-storage", *SERVICE_NAMES])
def test_command_is_registered(monkeypatch: pytest.MonkeyPatch, command: str) -> None:
    """``--help`` on each command proves it is wired up without running it."""
    monkeypatch.setenv("COLUMNS", "200")
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code != 0
    assert "Usage" in result.stdout
