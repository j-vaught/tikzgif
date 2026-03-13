import pytest

from tikzgif.cli.main import main


def test_cli_help_runs() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_cli_render_help_runs() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["render", "--help"])
    assert exc.value.code == 0
