from pathlib import Path

import pytest

from tikzgif.assembly import AnimationAssembler, OutputConfig
from tikzgif.exceptions import AssemblyError


def test_animation_assembler_rejects_unknown_format(tmp_path: Path) -> None:
    config = OutputConfig(output_path=tmp_path / "out.gif")
    assembler = AnimationAssembler(config)
    assembler.config.format = None  # type: ignore[assignment]

    with pytest.raises(AssemblyError, match="Unsupported output format"):
        assembler.assemble([])
