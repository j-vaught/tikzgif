from pathlib import Path

import pytest

from tikzgif.api import render


def test_render_rejects_missing_input_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.tex"
    with pytest.raises(FileNotFoundError):
        render(missing)


def test_render_rejects_unsupported_format(tmp_path: Path) -> None:
    tex = tmp_path / "demo.tex"
    tex.write_text("""\\documentclass{standalone}
\\begin{document}
\\begin{tikzpicture}
\\draw (0,0) -- (\\PARAM,1);
\\end{tikzpicture}
\\end{document}
""", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported format"):
        render(tex, format="webp")


def test_render_rejects_non_positive_frames(tmp_path: Path) -> None:
    tex = tmp_path / "demo.tex"
    tex.write_text("""\\documentclass{standalone}
\\begin{document}
\\begin{tikzpicture}
\\draw (0,0) -- (\\PARAM,1);
\\end{tikzpicture}
\\end{document}
""", encoding="utf-8")

    with pytest.raises(ValueError, match="frames must be >= 1"):
        render(tex, frames=0)
