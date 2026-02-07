# tikzgif -- Design Specification

Version 0.1.0-draft
Author: J.C. Vaught
Date: 2026-02-06

---

## Table of Contents

1. [CLI Interface](#1-cli-interface)
2. [Python API](#2-python-api)
3. [Input Specification Format](#3-input-specification-format)
4. [Output Specification](#4-output-specification)

---

## 1. CLI Interface

### 1.1 Installation

```bash
pip install tikzgif
```

This installs the `tikzgif` command and the `tikzgif` Python package.

### 1.2 Command Syntax

```
tikzgif <COMMAND> [OPTIONS] <INPUT>
```

There are four top-level commands:

| Command   | Purpose                                      |
|-----------|----------------------------------------------|
| `render`  | Compile a .tex file into an animated output  |
| `preview` | Open a live preview window (or serve HTTP)   |
| `watch`   | Re-render automatically on file change       |
| `inspect` | Parse a .tex file and print detected params  |
| `init`    | Scaffold a tikzgif.toml config in the cwd    |
| `clean`   | Remove intermediate build artifacts          |

`render` is the default when no command is given. That is:

```bash
tikzgif my_animation.tex          # identical to:
tikzgif render my_animation.tex
```

### 1.3 `render` Command -- Full Flag Reference

```
tikzgif render [OPTIONS] <INPUT>

Positional:
  INPUT                     Path to .tex file, .toml manifest, or directory
                            containing tikzgif.toml

Required (one of):
  -p, --param NAME=START:END:STEPS
                            Animation parameter sweep specification.
                            May be repeated for multi-parameter animations.
                            Example: -p angle=0:360:72
                            Overridden by magic comments in the .tex file
                            or by a manifest file.

Output Control:
  -o, --output PATH         Output file path.
                            Default: <input_stem>.gif
  -f, --format FORMAT       Output format: gif, mp4, webp, apng
                            Default: gif (inferred from -o extension if given)
  --fps N                   Frames per second in the output.
                            Default: 24
  --loop N                  Loop count. 0 = infinite loop.
                            Default: 0
  --duration MS             Total animation duration in milliseconds.
                            Mutually exclusive with --fps when --steps is set;
                            the system computes whichever is missing.
                            Default: computed from fps and step count.

Rendering:
  --dpi N                   Resolution for PDF-to-image rasterization.
                            Default: 150
  --density N               Alias for --dpi (ImageMagick convention).
  --width PX                Force output width in pixels (aspect-preserving).
  --height PX               Force output height in pixels (aspect-preserving).
  --bg COLOR                Background color. Accepts hex (#FFFFFF), rgb(r,g,b),
                            or named CSS colors. "transparent" for alpha.
                            Default: white
  --quality N               Compression quality 1-100. Meaning varies by format:
                            GIF: color quantization quality (higher = slower, better)
                            MP4: CRF value inverted (100 = lossless)
                            WebP: lossy quality
                            Default: 85
  --colors N                Max palette colors for GIF output (2-256).
                            Default: 256
  --optimize                Enable GIF frame optimization (delta frames).
                            Default: true
  --no-optimize             Disable GIF frame optimization.

LaTeX:
  --engine ENGINE           LaTeX engine: pdflatex, lualatex, xelatex.
                            Default: pdflatex
  --shell-escape            Pass --shell-escape to the LaTeX engine.
  --tex-args ARGS           Additional raw arguments passed to the LaTeX engine.
                            Quote the whole string: --tex-args "--synctex=1"
  --preamble FILE           Path to an additional preamble file to \input.

Build:
  --jobs N, -j N            Parallel compilation workers.
                            Default: number of CPU cores
  --keep-frames             Do not delete intermediate frame PNGs after assembly.
  --build-dir DIR           Directory for intermediate files.
                            Default: .tikzgif_build/
  --clean-before            Remove build dir before starting.

Behavior:
  --dry-run                 Print the compilation plan without executing.
  --force                   Overwrite output file without prompting.
  -v, --verbose             Increase verbosity. May be repeated:
                            (none) = WARNING, -v = INFO, -vv = DEBUG
  -q, --quiet               Suppress all output except errors.
  --log FILE                Write log output to FILE in addition to stderr.
  --progress / --no-progress
                            Show/hide the progress bar.
                            Default: show when stderr is a TTY.

Config:
  --config FILE             Path to tikzgif.toml config file.
                            Default: search upward from INPUT for tikzgif.toml
  --no-config               Ignore all config files.
```

### 1.4 Multi-Parameter Sweeps

Parameters are swept as a Cartesian product by default, or zipped:

```bash
# Cartesian product: 72 * 10 = 720 frames
tikzgif render -p angle=0:360:72 -p scale=0.5:2.0:10 shape.tex

# Zipped (parallel sweep, must have same step count):
tikzgif render -p angle=0:360:72 -p opacity=0:1:72 --sweep zip shape.tex

# The --sweep flag:
#   product  (default) -- Cartesian product of all params
#   zip      -- parallel zip, all params must have equal step count
#   chain    -- concatenate: first sweep angle, then sweep opacity
```

### 1.5 Other Commands

```bash
# Watch mode: re-render on file save
tikzgif watch my_animation.tex -p angle=0:360:72 --fps 30

# Inspect: show what tikzgif detected from the file
tikzgif inspect my_animation.tex
# Output:
#   Parameters detected:
#     angle  (magic comment)  range=0:360  steps=72
#   Estimated frames: 72
#   Estimated build time: ~45s (at 4 workers)

# Init: create a starter config
tikzgif init
# Creates tikzgif.toml in the current directory

# Clean: remove build artifacts
tikzgif clean                    # cleans .tikzgif_build/
tikzgif clean --all              # also removes output files

# Preview: render and open in system viewer, or start HTTP server
tikzgif preview my_animation.tex -p angle=0:360:72
tikzgif preview my_animation.tex --serve --port 8080
```

### 1.6 Usage Examples

```bash
# Simplest possible invocation (param defined in .tex magic comment):
tikzgif pendulum.tex

# Explicit parameter, custom output:
tikzgif -p theta=0:6.28:60 -o pendulum.gif --fps 30 --dpi 300 pendulum.tex

# MP4 output at 60fps:
tikzgif -p t=0:10:300 -f mp4 --fps 60 --quality 95 simulation.tex

# WebP with transparency:
tikzgif -p frame=1:100:100 --bg transparent -f webp diagram.tex

# Dry run to see the plan:
tikzgif --dry-run -p angle=0:360:72 shape.tex

# Using a manifest file instead of CLI flags:
tikzgif render animation.toml

# Using a directory (must contain tikzgif.toml):
tikzgif render ./my_project/

# Parallel build with 8 workers, keeping frames:
tikzgif -p t=0:1:200 -j 8 --keep-frames --build-dir ./frames/ sim.tex

# Pipe-friendly (quiet mode, force overwrite):
tikzgif -q --force -p n=1:50:50 -o out.gif fractal.tex

# Watch mode with live preview:
tikzgif watch -p angle=0:360:36 --fps 10 rotating_cube.tex
```

### 1.7 Config File Format (TOML)

File: `tikzgif.toml`

```toml
# tikzgif project configuration
# Place in your project root. tikzgif searches upward from the .tex file.

[project]
name = "rotating-cube"
version = "1.0"

[input]
file = "rotating_cube.tex"         # relative to this file's directory
engine = "pdflatex"
shell_escape = false
# extra_args = "--synctex=1"
# preamble = "my_preamble.tex"

[params]
# Each key is a parameter name; value is "start:end:steps"
angle = "0:360:72"
# For multiple params:
# scale = "0.5:2.0:10"

[params.sweep]
mode = "product"                    # "product", "zip", or "chain"

[output]
file = "rotating_cube.gif"         # relative to this file's directory
format = "gif"                      # gif, mp4, webp, apng
fps = 24
loop = 0                            # 0 = infinite
# duration = 3000                   # alternative to fps: total ms

[render]
dpi = 150
# width = 800
# height = 600
background = "white"                # hex, rgb(), named color, "transparent"
quality = 85
colors = 256                        # GIF only
optimize = true                     # GIF delta-frame optimization

[build]
jobs = 4                            # parallel workers (0 = auto-detect)
keep_frames = false
build_dir = ".tikzgif_build"
clean_before = false

[logging]
verbosity = "info"                  # "debug", "info", "warning", "error", "quiet"
# log_file = "tikzgif.log"
progress = true
```

**Precedence order** (highest wins):

1. CLI flags
2. Magic comments in the .tex file
3. Manifest .toml file
4. Project tikzgif.toml (found by upward search)
5. `~/.config/tikzgif/config.toml` (user-global defaults)
6. Built-in defaults

### 1.8 Verbosity and Logging

| Flag       | Level   | Behavior                                          |
|------------|---------|---------------------------------------------------|
| `-q`       | QUIET   | Only fatal errors                                 |
| (default)  | WARNING | Warnings and errors                               |
| `-v`       | INFO    | Progress, parameter detection, timing             |
| `-vv`      | DEBUG   | Every LaTeX invocation, file I/O, ImageMagick cmd |

The `--log FILE` flag mirrors all output (at the current verbosity) to a file. The progress bar is never written to the log file.

### 1.9 Watch Mode Detail

```bash
tikzgif watch [same options as render] <INPUT>
```

Behavior:
- Uses filesystem events (watchdog library) to detect changes to the .tex file, any `\input`/`\include` dependencies, the tikzgif.toml, and the preamble file.
- On change, debounces for 300ms, then triggers a full re-render.
- Holds a persistent preview window (via Pillow or system viewer) that refreshes.
- Ctrl+C exits cleanly, removing build artifacts unless `--keep-frames`.

### 1.10 Dry-Run Mode Detail

```bash
tikzgif --dry-run -p angle=0:360:72 shape.tex
```

Output:
```
[dry-run] Input: shape.tex
[dry-run] Engine: pdflatex
[dry-run] Parameter: angle = 0.0 -> 360.0 (72 steps, delta=5.0)
[dry-run] Total frames: 72
[dry-run] Build dir: .tikzgif_build/
[dry-run] Parallel workers: 8
[dry-run] Pipeline per frame:
           1. Substitute angle=<value> into shape.tex -> .tikzgif_build/frame_0001.tex
           2. pdflatex -interaction=nonstopmode .tikzgif_build/frame_0001.tex
           3. pdf2image @ 150 DPI -> .tikzgif_build/frame_0001.png
[dry-run] Assembly: 72 PNGs -> shape.gif (GIF, 24fps, loop=0, 256 colors)
[dry-run] Estimated output: ~72 frames, ~3.0s duration
[dry-run] No files were created.
```

---

## 2. Python API

### 2.1 Package Structure

```
tikzgif/
    __init__.py              # Public API re-exports
    __main__.py              # python -m tikzgif entry point
    cli.py                   # Click-based CLI definition
    config.py                # Config loading, merging, validation
    models.py                # Dataclasses: Animation, Frame, ParamSweep, etc.
    parser.py                # .tex file parser (magic comments, \newcommand detection)
    engine.py                # LaTeX compilation engine abstraction
    rasterizer.py            # PDF -> image conversion
    assembler.py             # Image sequence -> GIF/MP4/WebP/APNG
    watcher.py               # File-watching logic
    parallel.py              # Parallel frame compilation orchestrator
    notebook.py              # Jupyter integration (display, widgets)
    _logging.py              # Logging setup
    _types.py                # Shared type aliases
    _version.py              # Single-source version
    py.typed                 # PEP 561 marker
```

### 2.2 Core Type Definitions (`_types.py`)

```python
"""Shared type aliases for tikzgif."""
from __future__ import annotations

import os
from typing import Literal, TypeAlias

StrPath: TypeAlias = str | os.PathLike[str]
Color: TypeAlias = str  # "#RRGGBB", "rgb(r,g,b)", named, "transparent"
LatexEngine: TypeAlias = Literal["pdflatex", "lualatex", "xelatex"]
OutputFormat: TypeAlias = Literal["gif", "mp4", "webp", "apng"]
SweepMode: TypeAlias = Literal["product", "zip", "chain"]
Verbosity: TypeAlias = Literal["quiet", "warning", "info", "debug"]
```

### 2.3 Data Models (`models.py`)

```python
"""Core data models for tikzgif."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

from tikzgif._types import (
    Color,
    LatexEngine,
    OutputFormat,
    StrPath,
    SweepMode,
)


@dataclass(frozen=True, slots=True)
class ParamSweep:
    """A single parameter sweep specification.

    Attributes:
        name:  The LaTeX command/variable name (without backslash).
        start: Starting value (inclusive).
        end:   Ending value (inclusive).
        steps: Number of discrete steps (number of frames for this param).
    """

    name: str
    start: float
    end: float
    steps: int

    def __post_init__(self) -> None:
        if self.steps < 1:
            raise ValueError(f"steps must be >= 1, got {self.steps}")

    @property
    def delta(self) -> float:
        """Step size between consecutive values."""
        if self.steps == 1:
            return 0.0
        return (self.end - self.start) / (self.steps - 1)

    @property
    def values(self) -> list[float]:
        """All parameter values in the sweep."""
        if self.steps == 1:
            return [self.start]
        return [
            self.start + i * self.delta for i in range(self.steps)
        ]

    @classmethod
    def from_string(cls, name: str, spec: str) -> ParamSweep:
        """Parse 'start:end:steps' into a ParamSweep.

        >>> ParamSweep.from_string("angle", "0:360:72")
        ParamSweep(name='angle', start=0.0, end=360.0, steps=72)
        """
        parts = spec.split(":")
        if len(parts) != 3:
            raise ValueError(
                f"Expected 'start:end:steps', got '{spec}'"
            )
        return cls(
            name=name,
            start=float(parts[0]),
            end=float(parts[1]),
            steps=int(parts[2]),
        )


@dataclass(frozen=True, slots=True)
class FrameSpec:
    """The parameter assignment for a single frame.

    Attributes:
        index:  Zero-based frame index.
        params: Mapping of parameter name -> value for this frame.
    """

    index: int
    params: dict[str, float]


@dataclass(slots=True)
class RenderConfig:
    """All settings for a single render job.

    This is the fully-resolved configuration after merging CLI flags,
    config files, and magic comments. Every field has a concrete value.
    """

    # Input
    input_file: Path
    engine: LatexEngine = "pdflatex"
    shell_escape: bool = False
    extra_tex_args: list[str] = field(default_factory=list)
    preamble: Path | None = None

    # Parameters
    sweeps: list[ParamSweep] = field(default_factory=list)
    sweep_mode: SweepMode = "product"

    # Output
    output_file: Path | None = None  # None = auto-named
    output_format: OutputFormat = "gif"
    fps: int = 24
    loop: int = 0
    duration_ms: int | None = None  # overrides fps if set

    # Rendering
    dpi: int = 150
    width: int | None = None
    height: int | None = None
    background: Color = "white"
    quality: int = 85
    colors: int = 256
    optimize: bool = True

    # Build
    jobs: int = 0  # 0 = auto-detect
    keep_frames: bool = False
    build_dir: Path = Path(".tikzgif_build")
    clean_before: bool = False

    @property
    def effective_jobs(self) -> int:
        import os
        return self.jobs if self.jobs > 0 else os.cpu_count() or 1

    @property
    def resolved_output(self) -> Path:
        if self.output_file is not None:
            return self.output_file
        stem = self.input_file.stem
        ext = self.output_format
        return self.input_file.parent / f"{stem}.{ext}"

    def frame_specs(self) -> list[FrameSpec]:
        """Generate all FrameSpec objects for the configured sweep."""
        if not self.sweeps:
            raise ValueError("No parameter sweeps configured")

        if self.sweep_mode == "product":
            return self._product_frames()
        elif self.sweep_mode == "zip":
            return self._zip_frames()
        elif self.sweep_mode == "chain":
            return self._chain_frames()
        else:
            raise ValueError(f"Unknown sweep mode: {self.sweep_mode}")

    def _product_frames(self) -> list[FrameSpec]:
        """Cartesian product of all sweeps."""
        import itertools

        all_values: list[list[tuple[str, float]]] = []
        for sweep in self.sweeps:
            all_values.append(
                [(sweep.name, v) for v in sweep.values]
            )

        frames: list[FrameSpec] = []
        for idx, combo in enumerate(itertools.product(*all_values)):
            frames.append(
                FrameSpec(index=idx, params=dict(combo))
            )
        return frames

    def _zip_frames(self) -> list[FrameSpec]:
        """Parallel zip of all sweeps (must have equal step counts)."""
        counts = {s.steps for s in self.sweeps}
        if len(counts) != 1:
            raise ValueError(
                f"zip mode requires equal step counts, got {counts}"
            )
        n = counts.pop()
        frames: list[FrameSpec] = []
        for i in range(n):
            params = {s.name: s.values[i] for s in self.sweeps}
            frames.append(FrameSpec(index=i, params=params))
        return frames

    def _chain_frames(self) -> list[FrameSpec]:
        """Concatenate sweeps sequentially."""
        frames: list[FrameSpec] = []
        idx = 0
        for sweep in self.sweeps:
            for val in sweep.values:
                # All other params held at their start value
                params = {s.name: s.start for s in self.sweeps}
                params[sweep.name] = val
                frames.append(FrameSpec(index=idx, params=params))
                idx += 1
        return frames


@dataclass(slots=True)
class Frame:
    """A single rendered frame.

    Populated during the render pipeline.
    """

    spec: FrameSpec
    tex_path: Path | None = None
    pdf_path: Path | None = None
    image_path: Path | None = None

    @property
    def index(self) -> int:
        return self.spec.index


@dataclass(slots=True)
class AnimationResult:
    """The result of a completed render job."""

    output_path: Path
    frame_count: int
    duration_seconds: float
    file_size_bytes: int
    frames: list[Frame] = field(default_factory=list)
```

### 2.4 Public API (`__init__.py`)

```python
"""tikzgif -- Convert parameterized TikZ/LaTeX to animated GIFs.

Basic usage::

    import tikzgif

    result = tikzgif.render(
        "pendulum.tex",
        params={"theta": (0, 6.28, 60)},
        fps=30,
        dpi=300,
    )
    print(result.output_path)

"""
from tikzgif._version import __version__
from tikzgif.models import (
    AnimationResult,
    Frame,
    FrameSpec,
    ParamSweep,
    RenderConfig,
)
from tikzgif.api import (
    render,
    render_async,
    Animation,
)

__all__ = [
    "__version__",
    "render",
    "render_async",
    "Animation",
    "AnimationResult",
    "Frame",
    "FrameSpec",
    "ParamSweep",
    "RenderConfig",
]
```

### 2.5 Functional API (`api.py`)

```python
"""High-level functional and object-oriented API for tikzgif."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Sequence, overload

from tikzgif._types import (
    Color,
    LatexEngine,
    OutputFormat,
    StrPath,
    SweepMode,
)
from tikzgif.models import (
    AnimationResult,
    Frame,
    FrameSpec,
    ParamSweep,
    RenderConfig,
)


# ---------------------------------------------------------------------------
# Functional API
# ---------------------------------------------------------------------------

def render(
    input_file: StrPath,
    *,
    params: dict[str, tuple[float, float, int]] | None = None,
    output: StrPath | None = None,
    format: OutputFormat = "gif",
    fps: int = 24,
    loop: int = 0,
    duration_ms: int | None = None,
    dpi: int = 150,
    width: int | None = None,
    height: int | None = None,
    background: Color = "white",
    quality: int = 85,
    colors: int = 256,
    optimize: bool = True,
    engine: LatexEngine = "pdflatex",
    shell_escape: bool = False,
    jobs: int = 0,
    keep_frames: bool = False,
    build_dir: StrPath = ".tikzgif_build",
    sweep_mode: SweepMode = "product",
    verbose: bool = False,
) -> AnimationResult:
    """Render a parameterized .tex file into an animated image.

    This is the primary entry point for programmatic use. It blocks until
    the render is complete and returns an AnimationResult.

    Args:
        input_file:   Path to the .tex source file.
        params:       Dict mapping parameter names to (start, end, steps).
                      Example: {"angle": (0, 360, 72)}
                      If None, parameters are read from magic comments
                      in the .tex file or from tikzgif.toml.
        output:       Output file path. If None, auto-named from input.
        format:       Output format.
        fps:          Frames per second.
        loop:         Loop count (0 = infinite).
        duration_ms:  Total duration in ms (overrides fps if set).
        dpi:          Rasterization resolution.
        width:        Force output width in pixels.
        height:       Force output height in pixels.
        background:   Background color.
        quality:      Compression quality (1-100).
        colors:       Max GIF palette colors.
        optimize:     Enable GIF delta-frame optimization.
        engine:       LaTeX engine.
        shell_escape: Pass --shell-escape to LaTeX.
        jobs:         Parallel workers (0 = auto).
        keep_frames:  Preserve intermediate frame images.
        build_dir:    Directory for intermediate files.
        sweep_mode:   How to combine multi-param sweeps.
        verbose:      Enable info-level logging.

    Returns:
        AnimationResult with output path, frame count, etc.

    Raises:
        FileNotFoundError: If input_file does not exist.
        tikzgif.LatexCompilationError: If any frame fails to compile.
        tikzgif.RasterizationError: If PDF-to-image conversion fails.
        ValueError: If parameters are invalid.

    Example::

        result = tikzgif.render(
            "shape.tex",
            params={"angle": (0, 360, 72)},
            fps=30,
            dpi=300,
            output="shape.gif",
        )
        print(f"Created {result.output_path} ({result.frame_count} frames)")
    """
    config = _build_config(
        input_file=input_file,
        params=params,
        output=output,
        format=format,
        fps=fps,
        loop=loop,
        duration_ms=duration_ms,
        dpi=dpi,
        width=width,
        height=height,
        background=background,
        quality=quality,
        colors=colors,
        optimize=optimize,
        engine=engine,
        shell_escape=shell_escape,
        jobs=jobs,
        keep_frames=keep_frames,
        build_dir=build_dir,
        sweep_mode=sweep_mode,
    )
    from tikzgif.pipeline import execute_render
    return execute_render(config, verbose=verbose)


async def render_async(
    input_file: StrPath,
    *,
    params: dict[str, tuple[float, float, int]] | None = None,
    **kwargs: Any,
) -> AnimationResult:
    """Async version of render(). Same signature.

    Useful in Jupyter notebooks (which run an event loop) and in
    async web applications.

    Example::

        result = await tikzgif.render_async(
            "shape.tex",
            params={"angle": (0, 360, 72)},
        )
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: render(input_file, params=params, **kwargs)
    )


# ---------------------------------------------------------------------------
# Builder / OOP API
# ---------------------------------------------------------------------------

class Animation:
    """Builder-pattern API for constructing animations.

    Provides a fluent interface for configuring and rendering animations,
    and integrates with Jupyter notebooks for inline display.

    Example::

        anim = (
            tikzgif.Animation("shape.tex")
            .param("angle", 0, 360, steps=72)
            .param("scale", 0.5, 2.0, steps=10)
            .sweep("product")
            .fps(30)
            .dpi(300)
            .background("#000000")
            .format("gif")
        )

        # Render to file
        result = anim.render("output.gif")

        # Display inline in Jupyter
        anim.display()

        # Iterate over frames without assembling
        for frame in anim.frames():
            process(frame.image_path)
    """

    def __init__(self, input_file: StrPath) -> None:
        self._input_file = Path(input_file)
        self._sweeps: list[ParamSweep] = []
        self._sweep_mode: SweepMode = "product"
        self._output: Path | None = None
        self._format: OutputFormat = "gif"
        self._fps: int = 24
        self._loop: int = 0
        self._duration_ms: int | None = None
        self._dpi: int = 150
        self._width: int | None = None
        self._height: int | None = None
        self._background: Color = "white"
        self._quality: int = 85
        self._colors: int = 256
        self._optimize: bool = True
        self._engine: LatexEngine = "pdflatex"
        self._shell_escape: bool = False
        self._jobs: int = 0
        self._keep_frames: bool = False
        self._build_dir: Path = Path(".tikzgif_build")
        self._preamble: Path | None = None
        self._extra_tex_args: list[str] = []

    # -- Fluent setters (all return self for chaining) --

    def param(
        self,
        name: str,
        start: float,
        end: float,
        *,
        steps: int,
    ) -> Animation:
        """Add a parameter sweep."""
        self._sweeps.append(ParamSweep(name, start, end, steps))
        return self

    def sweep(self, mode: SweepMode) -> Animation:
        """Set sweep combination mode."""
        self._sweep_mode = mode
        return self

    def fps(self, fps: int) -> Animation:
        """Set frames per second."""
        self._fps = fps
        return self

    def dpi(self, dpi: int) -> Animation:
        """Set rasterization DPI."""
        self._dpi = dpi
        return self

    def size(
        self, width: int | None = None, height: int | None = None
    ) -> Animation:
        """Set output dimensions (aspect-preserving)."""
        self._width = width
        self._height = height
        return self

    def background(self, color: Color) -> Animation:
        """Set background color."""
        self._background = color
        return self

    def format(self, fmt: OutputFormat) -> Animation:
        """Set output format."""
        self._format = fmt
        return self

    def quality(self, q: int) -> Animation:
        """Set compression quality (1-100)."""
        self._quality = q
        return self

    def colors(self, n: int) -> Animation:
        """Set max GIF palette colors."""
        self._colors = n
        return self

    def loop(self, n: int) -> Animation:
        """Set loop count (0 = infinite)."""
        self._loop = n
        return self

    def duration(self, ms: int) -> Animation:
        """Set total animation duration in milliseconds."""
        self._duration_ms = ms
        return self

    def engine(self, eng: LatexEngine) -> Animation:
        """Set LaTeX engine."""
        self._engine = eng
        return self

    def shell_escape(self, enabled: bool = True) -> Animation:
        """Enable --shell-escape."""
        self._shell_escape = enabled
        return self

    def preamble(self, path: StrPath) -> Animation:
        """Set additional preamble file."""
        self._preamble = Path(path)
        return self

    def jobs(self, n: int) -> Animation:
        """Set parallel worker count (0 = auto)."""
        self._jobs = n
        return self

    def keep_frames(self, keep: bool = True) -> Animation:
        """Keep intermediate frame images after assembly."""
        self._keep_frames = keep
        return self

    def build_dir(self, path: StrPath) -> Animation:
        """Set build directory."""
        self._build_dir = Path(path)
        return self

    # -- Actions --

    def _to_config(self) -> RenderConfig:
        """Convert builder state to a RenderConfig."""
        return RenderConfig(
            input_file=self._input_file,
            engine=self._engine,
            shell_escape=self._shell_escape,
            extra_tex_args=self._extra_tex_args,
            preamble=self._preamble,
            sweeps=list(self._sweeps),
            sweep_mode=self._sweep_mode,
            output_file=self._output,
            output_format=self._format,
            fps=self._fps,
            loop=self._loop,
            duration_ms=self._duration_ms,
            dpi=self._dpi,
            width=self._width,
            height=self._height,
            background=self._background,
            quality=self._quality,
            colors=self._colors,
            optimize=self._optimize,
            jobs=self._jobs,
            keep_frames=self._keep_frames,
            build_dir=self._build_dir,
        )

    def render(self, output: StrPath | None = None) -> AnimationResult:
        """Execute the render pipeline and return the result.

        Args:
            output: Optional output path (overrides earlier config).

        Returns:
            AnimationResult
        """
        if output is not None:
            self._output = Path(output)
        config = self._to_config()
        from tikzgif.pipeline import execute_render
        return execute_render(config)

    async def render_async(
        self, output: StrPath | None = None
    ) -> AnimationResult:
        """Async version of render()."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.render(output)
        )

    def frames(self) -> Generator[Frame, None, None]:
        """Yield individual Frame objects without assembling.

        Each Frame has its .image_path populated. Useful for custom
        post-processing pipelines.
        """
        config = self._to_config()
        config.keep_frames = True
        from tikzgif.pipeline import render_frames_only
        yield from render_frames_only(config)

    def display(self, **kwargs: Any) -> None:
        """Display the animation inline in a Jupyter notebook.

        Renders (if not already rendered) and uses IPython.display
        to show the result.
        """
        from tikzgif.notebook import display_animation
        display_animation(self, **kwargs)

    def _repr_html_(self) -> str:
        """Jupyter rich display integration.

        When the Animation object is the last expression in a cell,
        Jupyter calls this method to render it inline.
        """
        from tikzgif.notebook import animation_to_html
        return animation_to_html(self)

    def plan(self) -> str:
        """Return a dry-run plan string (like --dry-run)."""
        config = self._to_config()
        from tikzgif.pipeline import format_plan
        return format_plan(config)

    def __repr__(self) -> str:
        params = ", ".join(
            f"{s.name}={s.start}:{s.end}:{s.steps}"
            for s in self._sweeps
        )
        return (
            f"Animation({self._input_file.name!r}, "
            f"params=[{params}], "
            f"format={self._format!r}, "
            f"fps={self._fps})"
        )


# ---------------------------------------------------------------------------
# Context Manager for Temporary Animations
# ---------------------------------------------------------------------------

@contextmanager
def animation_context(
    input_file: StrPath, **kwargs: Any
) -> Generator[Animation, None, None]:
    """Context manager that auto-cleans build artifacts on exit.

    Example::

        with tikzgif.animation_context("shape.tex") as anim:
            anim.param("angle", 0, 360, steps=72)
            result = anim.render()
            # use result.output_path
        # build dir is cleaned up here
    """
    anim = Animation(input_file)
    try:
        yield anim
    finally:
        import shutil
        build_dir = anim._build_dir
        if build_dir.exists():
            shutil.rmtree(build_dir)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_config(
    input_file: StrPath,
    params: dict[str, tuple[float, float, int]] | None,
    **kwargs: Any,
) -> RenderConfig:
    """Build a RenderConfig from the functional API arguments."""
    sweeps: list[ParamSweep] = []
    if params is not None:
        for name, (start, end, steps) in params.items():
            sweeps.append(ParamSweep(name, start, end, steps))

    path = Path(input_file)
    if not sweeps:
        # Attempt to detect from magic comments or config
        from tikzgif.parser import detect_params
        sweeps = detect_params(path)

    return RenderConfig(
        input_file=path,
        sweeps=sweeps,
        output_file=Path(kwargs["output"]) if kwargs.get("output") else None,
        output_format=kwargs.get("format", "gif"),
        fps=kwargs.get("fps", 24),
        loop=kwargs.get("loop", 0),
        duration_ms=kwargs.get("duration_ms"),
        dpi=kwargs.get("dpi", 150),
        width=kwargs.get("width"),
        height=kwargs.get("height"),
        background=kwargs.get("background", "white"),
        quality=kwargs.get("quality", 85),
        colors=kwargs.get("colors", 256),
        optimize=kwargs.get("optimize", True),
        engine=kwargs.get("engine", "pdflatex"),
        shell_escape=kwargs.get("shell_escape", False),
        jobs=kwargs.get("jobs", 0),
        keep_frames=kwargs.get("keep_frames", False),
        build_dir=Path(kwargs.get("build_dir", ".tikzgif_build")),
        sweep_mode=kwargs.get("sweep_mode", "product"),
    )
```

### 2.6 Jupyter Notebook Integration (`notebook.py`)

```python
"""Jupyter notebook integration for tikzgif."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tikzgif.api import Animation
    from tikzgif.models import AnimationResult


def display_animation(anim: Animation, **kwargs: Any) -> None:
    """Render and display an animation inline in Jupyter.

    Automatically detects the best display method:
    - GIF/APNG/WebP: displayed as <img> tag
    - MP4: displayed as <video> tag with controls
    """
    from IPython.display import display, HTML

    result = anim.render(**kwargs)
    html = _result_to_html(result, anim._format)
    display(HTML(html))


def animation_to_html(anim: Animation) -> str:
    """Generate HTML for Jupyter _repr_html_.

    Called automatically when an Animation is the last expression
    in a notebook cell.
    """
    try:
        result = anim.render()
        return _result_to_html(result, anim._format)
    except Exception as exc:
        return (
            f'<div style="color:red;font-family:monospace;">'
            f"tikzgif render failed: {exc}</div>"
        )


def _result_to_html(result: AnimationResult, fmt: str) -> str:
    """Convert a render result to an inline HTML snippet."""
    data = result.output_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")

    if fmt == "mp4":
        mime = "video/mp4"
        return (
            f'<video autoplay loop muted playsinline '
            f'style="max-width:100%;">'
            f'<source src="data:{mime};base64,{b64}" '
            f'type="{mime}">'
            f"</video>"
        )

    mime_map = {"gif": "image/gif", "webp": "image/webp", "apng": "image/png"}
    mime = mime_map.get(fmt, "image/gif")
    return (
        f'<img src="data:{mime};base64,{b64}" '
        f'style="max-width:100%;" />'
    )


def show_frame(
    anim: Animation,
    index: int = 0,
    *,
    width: int | None = None,
) -> None:
    """Display a single frame inline in Jupyter.

    Useful for debugging and tuning a specific frame.

    Example::

        tikzgif.notebook.show_frame(anim, index=36)
    """
    from IPython.display import display, Image

    frames = list(anim.frames())
    if index >= len(frames) or index < 0:
        raise IndexError(
            f"Frame index {index} out of range [0, {len(frames)})"
        )
    frame = frames[index]
    assert frame.image_path is not None
    kwargs: dict[str, Any] = {}
    if width is not None:
        kwargs["width"] = width
    display(Image(filename=str(frame.image_path), **kwargs))


def interactive_scrubber(anim: Animation) -> Any:
    """Create an ipywidgets slider to scrub through frames.

    Returns the widget. Requires ipywidgets to be installed.

    Example::

        scrubber = tikzgif.notebook.interactive_scrubber(anim)
        display(scrubber)
    """
    import ipywidgets as widgets
    from IPython.display import display, Image, clear_output

    frames = list(anim.frames())
    output = widgets.Output()

    def on_change(change: dict[str, Any]) -> None:
        idx = change["new"]
        with output:
            clear_output(wait=True)
            frame = frames[idx]
            assert frame.image_path is not None
            display(Image(filename=str(frame.image_path)))

    slider = widgets.IntSlider(
        value=0,
        min=0,
        max=len(frames) - 1,
        step=1,
        description="Frame:",
        continuous_update=False,
    )
    slider.observe(on_change, names="value")

    # Trigger initial display
    on_change({"new": 0})

    return widgets.VBox([slider, output])
```

### 2.7 Usage Examples

#### Minimal Python script

```python
import tikzgif

tikzgif.render(
    "rotating_cube.tex",
    params={"angle": (0, 360, 72)},
)
```

#### Full-featured script

```python
import tikzgif

result = tikzgif.render(
    "physics_sim.tex",
    params={
        "time": (0, 10, 300),
        "amplitude": (0.5, 2.0, 300),
    },
    sweep_mode="zip",
    output="simulation.mp4",
    format="mp4",
    fps=60,
    dpi=300,
    quality=95,
    engine="lualatex",
    jobs=8,
)

print(f"Output:   {result.output_path}")
print(f"Frames:   {result.frame_count}")
print(f"Duration: {result.duration_seconds:.1f}s")
print(f"Size:     {result.file_size_bytes / 1024:.0f} KB")
```

#### Builder pattern

```python
import tikzgif

anim = (
    tikzgif.Animation("shape.tex")
    .param("angle", 0, 360, steps=72)
    .fps(30)
    .dpi(300)
    .background("#73000A")
    .format("gif")
    .quality(90)
)

# Preview the plan
print(anim.plan())

# Render
result = anim.render("shape.gif")
```

#### Context manager

```python
import tikzgif
from tikzgif.api import animation_context

with animation_context("diagram.tex") as anim:
    anim.param("t", 0, 1, steps=50)
    result = anim.render("diagram.gif")
    print(result.output_path)
# .tikzgif_build/ is auto-cleaned here
```

#### Jupyter notebook

```python
# Cell 1: Define animation
import tikzgif

anim = (
    tikzgif.Animation("pendulum.tex")
    .param("theta", 0, 6.28, steps=60)
    .fps(24)
    .dpi(150)
    .background("white")
)

# Cell 2: Display inline (calls _repr_html_ automatically)
anim

# Cell 3: Scrub through frames interactively
from tikzgif.notebook import interactive_scrubber
interactive_scrubber(anim)

# Cell 4: Inspect a single frame
from tikzgif.notebook import show_frame
show_frame(anim, index=30)

# Cell 5: Async render (useful in notebooks with running event loops)
result = await anim.render_async("pendulum.gif")
```

#### Custom frame processing pipeline

```python
import tikzgif
from PIL import Image

anim = (
    tikzgif.Animation("graph.tex")
    .param("n", 1, 100, steps=100)
    .dpi(300)
    .keep_frames()
)

processed_frames = []
for frame in anim.frames():
    img = Image.open(frame.image_path)
    # Custom post-processing
    img = img.convert("L")  # grayscale
    processed_frames.append(img)

# Assemble manually
processed_frames[0].save(
    "graph_bw.gif",
    save_all=True,
    append_images=processed_frames[1:],
    duration=1000 // 24,
    loop=0,
)
```

---

## 3. Input Specification Format

tikzgif supports four methods for specifying animation parameters, each suited to different workflows.

### 3.1 Method A: Magic Comments in the .tex File

The .tex file itself contains structured comments that tikzgif parses.

#### Syntax

```latex
%%% tikzgif: param=<name>, range=<start>:<end>, steps=<N>
```

Multiple parameters use multiple comment lines:

```latex
%%% tikzgif: param=angle, range=0:360, steps=72
%%% tikzgif: param=scale, range=0.5:2.0, steps=10
%%% tikzgif: sweep=product
%%% tikzgif: fps=30, dpi=300, format=gif
```

#### Full Example

```latex
\documentclass[tikz,border=5pt]{standalone}
\usepackage{tikz}

%%% tikzgif: param=angle, range=0:360, steps=72
%%% tikzgif: fps=30, dpi=200

% The parameter is injected as a \newcommand by tikzgif.
% You must declare a default for standalone compilation:
\providecommand{\angle}{0}

\begin{document}
\begin{tikzpicture}
  \draw[thick, rotate=\angle] (0,0) rectangle (2,2);
  \fill[red, rotate=\angle] (1,1) circle (0.3);
\end{tikzpicture}
\end{document}
```

#### How It Works

1. tikzgif scans the file for lines matching `^%%% tikzgif:`.
2. It parses the key=value pairs.
3. For each frame, tikzgif generates a modified .tex file where `\providecommand{\angle}{0}` is effectively overridden by prepending `\newcommand{\angle}{<value>}` before `\providecommand` (or by using `\renewcommand`).

Specifically, tikzgif injects this line immediately after `\documentclass`:

```latex
\newcommand{\tikzgifAngle}{45.0}  % injected by tikzgif, frame 9/72
```

And the user references `\tikzgifAngle` in their document. Alternatively, tikzgif can do direct text substitution using a placeholder syntax:

```latex
%%% tikzgif: param=angle, range=0:360, steps=72, mode=substitute

\begin{tikzpicture}
  \draw[thick, rotate={{ANGLE}}] (0,0) rectangle (2,2);
\end{tikzpicture}
```

Where `{{ANGLE}}` (double braces, uppercase name) is replaced with the numeric value.

#### Magic Comment Reference

```
%%% tikzgif: param=<name>, range=<start>:<end>, steps=<N>
                                                          [, mode=command|substitute]
%%% tikzgif: sweep=product|zip|chain
%%% tikzgif: fps=<N>
%%% tikzgif: dpi=<N>
%%% tikzgif: format=gif|mp4|webp|apng
%%% tikzgif: loop=<N>
%%% tikzgif: background=<color>
%%% tikzgif: engine=pdflatex|lualatex|xelatex
%%% tikzgif: quality=<N>
%%% tikzgif: output=<filename>
```

#### When to Use

- Best for **self-contained** animations where the .tex file should carry its own animation metadata.
- Ideal when sharing .tex files -- the recipient can run `tikzgif shape.tex` with no other configuration.
- The .tex file remains valid LaTeX and compiles normally (producing the default frame) because `\providecommand` supplies defaults.

#### Parser Implementation (`parser.py`)

```python
"""Parse .tex files for tikzgif magic comments and parameter injection."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tikzgif.models import ParamSweep

# Matches: %%% tikzgif: key=value, key=value, ...
_MAGIC_RE = re.compile(r"^%%% tikzgif:\s*(.+)$", re.MULTILINE)
_KV_RE = re.compile(r"(\w+)\s*=\s*([^,]+)")

# Matches: \providecommand{\name}{default}
_PROVIDE_RE = re.compile(
    r"\\providecommand\{\\(\w+)\}\{([^}]*)\}"
)

# Matches: {{NAME}} placeholder
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def detect_params(tex_path: Path) -> list[ParamSweep]:
    """Extract ParamSweep definitions from magic comments in a .tex file.

    Returns a list of ParamSweep objects. Returns empty list if no
    magic comments are found.
    """
    content = tex_path.read_text(encoding="utf-8")
    sweeps: list[ParamSweep] = []

    for match in _MAGIC_RE.finditer(content):
        line = match.group(1).strip()
        kvs = dict(_KV_RE.findall(line))

        if "param" in kvs and "range" in kvs and "steps" in kvs:
            name = kvs["param"].strip()
            range_spec = kvs["range"].strip()
            steps = int(kvs["steps"].strip())
            start_s, end_s = range_spec.split(":")
            sweeps.append(
                ParamSweep(
                    name=name,
                    start=float(start_s),
                    end=float(end_s),
                    steps=steps,
                )
            )

    return sweeps


def detect_settings(tex_path: Path) -> dict[str, Any]:
    """Extract non-parameter settings from magic comments.

    Returns a dict of settings like fps, dpi, format, etc.
    """
    content = tex_path.read_text(encoding="utf-8")
    settings: dict[str, Any] = {}
    param_keys = {"param", "range", "steps", "mode"}

    for match in _MAGIC_RE.finditer(content):
        line = match.group(1).strip()
        kvs = dict(_KV_RE.findall(line))
        for key, value in kvs.items():
            if key not in param_keys:
                # Type coerce
                value = value.strip()
                if value.isdigit():
                    settings[key] = int(value)
                else:
                    try:
                        settings[key] = float(value)
                    except ValueError:
                        settings[key] = value

    return settings


def inject_params_command(
    tex_content: str,
    params: dict[str, float],
    frame_index: int,
    total_frames: int,
) -> str:
    """Inject parameters as \\newcommand definitions after \\documentclass.

    The injected commands use the naming convention \\tikzgif<Name>
    (camelCase with tikzgif prefix) to avoid collisions.

    Also defines plain \\<name> via \\renewcommand if \\providecommand
    was used in the original.
    """
    injection_lines = [
        f"% -- tikzgif frame {frame_index + 1}/{total_frames} --"
    ]
    for name, value in params.items():
        # Format: remove trailing zeros but keep at least one decimal
        if value == int(value):
            formatted = f"{int(value)}"
        else:
            formatted = f"{value:.6f}".rstrip("0").rstrip(".")

        # Provide both tikzgif-prefixed and plain versions
        capitalized = name[0].upper() + name[1:] if name else name
        injection_lines.append(
            f"\\newcommand{{\\tikzgif{capitalized}}}{{{formatted}}}"
        )
        injection_lines.append(
            f"\\renewcommand{{\\{name}}}{{{formatted}}}"
        )

    injection_block = "\n".join(injection_lines) + "\n"

    # Insert after \documentclass line
    dc_pattern = re.compile(
        r"(\\documentclass(?:\[[^\]]*\])?\{[^}]*\}\s*\n)"
    )
    match = dc_pattern.search(tex_content)
    if match:
        insert_pos = match.end()
        return (
            tex_content[:insert_pos]
            + injection_block
            + tex_content[insert_pos:]
        )

    # Fallback: prepend
    return injection_block + tex_content


def inject_params_substitute(
    tex_content: str,
    params: dict[str, float],
) -> str:
    """Replace {{NAME}} placeholders with parameter values."""
    def replacer(m: re.Match[str]) -> str:
        name = m.group(1)
        # Try case-insensitive match
        for param_name, value in params.items():
            if param_name.upper() == name.upper():
                if value == int(value):
                    return str(int(value))
                return f"{value:.6f}".rstrip("0").rstrip(".")
        # No match -- leave placeholder intact
        return m.group(0)

    return _PLACEHOLDER_RE.sub(replacer, tex_content)
```

### 3.2 Method B: TOML Manifest File

A standalone TOML file that references the .tex file and contains all animation metadata.

#### Full Example: `rotating_cube.toml`

```toml
# tikzgif animation manifest

[input]
file = "rotating_cube.tex"
engine = "pdflatex"

[params]
angle = "0:360:72"

[params.sweep]
mode = "product"

[output]
file = "rotating_cube.gif"
fps = 30
dpi = 200
loop = 0
background = "white"
quality = 85
format = "gif"

[build]
jobs = 0
keep_frames = false
```

#### Usage

```bash
tikzgif render rotating_cube.toml
```

The manifest is also used as the project-level `tikzgif.toml` config (Section 1.7). When the input argument is a `.toml` file, tikzgif treats it as both config and manifest.

#### When to Use

- Best for **projects** where the .tex file is shared with collaborators who may not use tikzgif. The .tex stays clean of magic comments.
- Best when the same .tex file is used for multiple animations with different parameter ranges.
- Required for complex multi-file projects.

### 3.3 Method C: CLI Flags

Parameters are specified entirely on the command line.

#### Syntax

```bash
tikzgif -p angle=0:360:72 shape.tex
tikzgif -p angle=0:360:72 -p scale=0.5:2.0:10 --sweep product shape.tex
```

The `-p` / `--param` flag uses the format `NAME=START:END:STEPS`.

#### How the .tex File Declares Parameters

The .tex file must use one of these conventions for tikzgif to know where to inject values:

**Option 1: `\providecommand` (recommended)**

```latex
\providecommand{\angle}{0}  % default value for standalone compilation
```

tikzgif injects `\renewcommand{\angle}{45}` before this line.

**Option 2: `{{PLACEHOLDER}}` syntax**

```latex
\draw[rotate={{ANGLE}}] (0,0) -- (2,0);
```

tikzgif replaces `{{ANGLE}}` with the numeric value. This is triggered by adding `--mode substitute` or when the parameter name is detected in double-brace form.

**Option 3: No declaration needed**

If the .tex file uses `\tikzgifAngle` (the prefixed form), tikzgif simply injects the `\newcommand` and the .tex file need not declare anything. However, this means the .tex file will not compile standalone without tikzgif.

#### When to Use

- Best for **one-off** renders and quick experimentation.
- Best when calling tikzgif from scripts or Makefiles.
- Highest priority in the override chain -- CLI flags always win.

### 3.4 Method D: Python Wrapper

A thin Python script that generates the .tex content programmatically and feeds it to tikzgif.

#### Example: `generate_animation.py`

```python
"""Generate a parametric animation entirely from Python."""
import tikzgif
import textwrap

# Generate .tex content programmatically
def make_tex(n_sides: int) -> str:
    """Create a TikZ regular polygon with n sides."""
    angles = [360 * i / n_sides for i in range(n_sides)]
    coords = " -- ".join(
        f"({2*__import__('math').cos(__import__('math').radians(a)):.4f},"
        f"{2*__import__('math').sin(__import__('math').radians(a)):.4f})"
        for a in angles
    )
    return textwrap.dedent(f"""\
        \\documentclass[tikz,border=5pt]{{standalone}}
        \\usepackage{{tikz}}
        \\providecommand{{\\rotangle}}{{0}}
        \\begin{{document}}
        \\begin{{tikzpicture}}
          \\draw[thick, fill=blue!20, rotate=\\rotangle]
            {coords} -- cycle;
        \\end{{tikzpicture}}
        \\end{{document}}
    """)


# Write the .tex file
from pathlib import Path

tex_path = Path("polygon.tex")
tex_path.write_text(make_tex(6))

# Render with tikzgif
result = tikzgif.render(
    tex_path,
    params={"rotangle": (0, 360, 72)},
    fps=30,
    output="spinning_hexagon.gif",
)
```

#### Advanced: Template-Based Generation

```python
"""Use Jinja2 templates for complex parameterized TikZ."""
import tikzgif
from jinja2 import Template
from pathlib import Path

TEMPLATE = Template(r"""
\documentclass[tikz,border=5pt]{standalone}
\usepackage{tikz}
\providecommand{\timevar}{0}

\begin{document}
\begin{tikzpicture}
  {% for particle in particles %}
  \fill[{{ particle.color }}]
    ({{ particle.x }} + \timevar * {{ particle.vx }},
     {{ particle.y }} + \timevar * {{ particle.vy }})
    circle ({{ particle.radius }});
  {% endfor %}
\end{tikzpicture}
\end{document}
""")

# Generate particles
import random
random.seed(42)
particles = [
    {
        "x": random.uniform(-3, 3),
        "y": random.uniform(-3, 3),
        "vx": random.uniform(-0.5, 0.5),
        "vy": random.uniform(-0.5, 0.5),
        "radius": random.uniform(0.05, 0.2),
        "color": random.choice(["red", "blue", "green!60!black", "orange"]),
    }
    for _ in range(20)
]

tex_content = TEMPLATE.render(particles=particles)
tex_path = Path("particles.tex")
tex_path.write_text(tex_content)

result = tikzgif.render(
    tex_path,
    params={"timevar": (0, 5, 150)},
    fps=30,
    dpi=200,
    output="particles.gif",
)
```

#### When to Use

- Best for **programmatic** or **generative** content where the TikZ code itself varies.
- Best when integrating tikzgif into a larger Python pipeline.
- Best for parametric designs that require computation beyond what LaTeX macros can express.

### 3.5 Decision Matrix

| Method | Self-contained .tex | Clean .tex | No Python needed | Multi-animation | Scriptable |
|--------|:---:|:---:|:---:|:---:|:---:|
| A. Magic comments | Yes | No | Yes | No | Partial |
| B. TOML manifest  | No  | Yes | Yes | Yes | Partial |
| C. CLI flags       | No  | Yes | Yes | No  | Yes |
| D. Python wrapper  | No  | Yes | N/A | Yes | Yes |

### 3.6 Parameter Injection Modes

Regardless of input method, tikzgif uses one of two injection strategies:

| Mode | Trigger | Mechanism | .tex compiles standalone? |
|------|---------|-----------|:---:|
| `command` (default) | `\providecommand` present, or `mode=command` | Injects `\renewcommand` after `\documentclass` | Yes |
| `substitute` | `{{NAME}}` placeholder found, or `mode=substitute` | Text replacement of `{{NAME}}` with value | No (unless defaults provided via separate mechanism) |

Auto-detection logic:

```python
def detect_injection_mode(tex_content: str, param_name: str) -> str:
    """Determine whether to use command or substitute mode."""
    placeholder = "{{" + param_name.upper() + "}}"
    if placeholder in tex_content:
        return "substitute"
    return "command"
```

---

## 4. Output Specification

### 4.1 Default Output Naming

| Input | Default output |
|-------|----------------|
| `shape.tex` | `shape.gif` |
| `shape.tex` with `--format mp4` | `shape.mp4` |
| `animation.toml` (references `shape.tex`) | `shape.gif` (or as specified in TOML) |

When the output path is a directory, the file is placed inside it:

```bash
tikzgif -o ./output/ shape.tex
# produces ./output/shape.gif
```

### 4.2 Output Directory Structure

During a build, the working tree looks like this:

```
project/
    shape.tex                     # source
    tikzgif.toml                  # optional config
    shape.gif                     # final output (placed next to source)
    .tikzgif_build/               # intermediate files (auto-cleaned)
        frame_0001.tex            # modified .tex for frame 1
        frame_0001.pdf            # compiled PDF
        frame_0001.png            # rasterized image
        frame_0001.aux            # LaTeX auxiliary (cleaned)
        frame_0001.log            # LaTeX log (cleaned)
        frame_0002.tex
        frame_0002.pdf
        frame_0002.png
        ...
        manifest.json             # build metadata (see below)
```

### 4.3 Frame Naming Convention

```
frame_{INDEX:04d}.{ext}
```

- 4-digit zero-padded index (supports up to 9999 frames).
- For builds exceeding 9999 frames, the padding auto-expands to 5+ digits.
- The index is the global frame index in the final animation order.

### 4.4 Intermediate File Management

**Default behavior (`--keep-frames` not set):**

1. After assembly, the entire `.tikzgif_build/` directory is deleted.
2. Only the final output file remains.

**With `--keep-frames`:**

1. `.tex`, `.pdf` intermediates are still cleaned.
2. `.png` frame images are preserved in the build dir.
3. The `manifest.json` is preserved.

**With `--build-dir custom_dir/`:**

1. Intermediates go to `custom_dir/` instead of `.tikzgif_build/`.
2. Same cleanup rules apply.

**Cleanup of LaTeX auxiliaries:**

For each frame, these files are deleted immediately after successful PDF generation:
- `.aux`, `.log`, `.synctex.gz`, `.fls`, `.fdb_latexmk`, `.nav`, `.out`, `.snm`, `.toc`, `.vrb`

The `.tex` intermediate is deleted after PDF generation (unless `--keep-frames`).
The `.pdf` intermediate is deleted after rasterization (unless `--keep-frames`).

### 4.5 Build Manifest (`manifest.json`)

Written to the build directory before assembly begins. Enables resumable builds.

```json
{
  "tikzgif_version": "0.1.0",
  "created": "2026-02-06T14:30:00Z",
  "input_file": "shape.tex",
  "input_hash": "sha256:abc123...",
  "config_hash": "sha256:def456...",
  "parameters": {
    "angle": {
      "start": 0.0,
      "end": 360.0,
      "steps": 72,
      "values": [0.0, 5.0, 10.0, "..."]
    }
  },
  "sweep_mode": "product",
  "total_frames": 72,
  "engine": "pdflatex",
  "dpi": 150,
  "frames": [
    {
      "index": 0,
      "params": {"angle": 0.0},
      "tex": "frame_0001.tex",
      "pdf": "frame_0001.pdf",
      "png": "frame_0001.png",
      "status": "complete",
      "compile_time_ms": 1230
    },
    {
      "index": 1,
      "params": {"angle": 5.0},
      "tex": "frame_0002.tex",
      "pdf": "frame_0002.pdf",
      "png": "frame_0002.png",
      "status": "complete",
      "compile_time_ms": 1180
    }
  ],
  "assembly": {
    "format": "gif",
    "fps": 24,
    "output": "shape.gif",
    "status": "pending"
  }
}
```

**Incremental builds:** If tikzgif finds an existing `manifest.json` and the `input_hash` and `config_hash` match, it skips frames whose status is `"complete"` and whose `.png` file exists. This dramatically speeds up re-renders after small .tex edits (only changed frames recompile).

### 4.6 Metadata Embedding

#### GIF

GIF files support a comment extension block. tikzgif writes:

```
Generated by tikzgif v0.1.0
Source: shape.tex
Frames: 72
FPS: 24
Parameters: angle=0:360:72
```

Implementation: via Pillow's `comment` parameter in the GIF save call.

#### MP4

MP4 files support metadata atoms. tikzgif writes (via ffmpeg):

```
title:   shape (tikzgif animation)
comment: Generated by tikzgif v0.1.0 | angle=0:360:72
```

#### WebP

WebP supports XMP metadata. tikzgif writes a minimal XMP block with the source info.

#### APNG

APNG text chunks (tEXt) carry:

```
Software: tikzgif v0.1.0
Source: shape.tex
Comment: angle=0:360:72
```

### 4.7 Output Format Details

| Format | Library | Quality control | Transparency | Max colors |
|--------|---------|----------------|:---:|:---:|
| GIF | Pillow | `colors` (palette size), `optimize` (delta frames) | 1-bit alpha | 256 |
| MP4 | ffmpeg (subprocess) | `quality` -> CRF mapping | No | Unlimited |
| WebP | Pillow (libwebp) | `quality` (lossy 1-100) | Full alpha | Unlimited |
| APNG | Pillow | `quality` (PNG compression) | Full alpha | Unlimited |

**MP4 quality mapping:**

```python
def quality_to_crf(quality: int) -> int:
    """Map tikzgif quality (1-100) to ffmpeg CRF (51-0).

    quality=100 -> CRF 0  (lossless)
    quality=85  -> CRF 8  (visually lossless)
    quality=50  -> CRF 26 (good)
    quality=1   -> CRF 51 (worst)
    """
    return round(51 * (1 - quality / 100))
```

### 4.8 Assembler Implementation Sketch (`assembler.py`)

```python
"""Assemble image sequences into animated output formats."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from PIL import Image

from tikzgif._types import OutputFormat
from tikzgif.models import RenderConfig


def assemble(
    frame_paths: Sequence[Path],
    config: RenderConfig,
) -> Path:
    """Assemble frame images into the final animated output.

    Args:
        frame_paths: Ordered list of frame image file paths.
        config: Render configuration.

    Returns:
        Path to the output file.
    """
    output = config.resolved_output
    fmt = config.output_format

    if fmt == "gif":
        return _assemble_gif(frame_paths, output, config)
    elif fmt == "mp4":
        return _assemble_mp4(frame_paths, output, config)
    elif fmt == "webp":
        return _assemble_webp(frame_paths, output, config)
    elif fmt == "apng":
        return _assemble_apng(frame_paths, output, config)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def _assemble_gif(
    frame_paths: Sequence[Path],
    output: Path,
    config: RenderConfig,
) -> Path:
    """Assemble frames into an animated GIF using Pillow."""
    frames: list[Image.Image] = []
    for path in frame_paths:
        img = Image.open(path)
        if config.background != "transparent":
            img = img.convert("RGB")
        else:
            img = img.convert("RGBA")

        # Resize if requested
        if config.width or config.height:
            img = _resize(img, config.width, config.height)

        # Quantize for GIF
        if img.mode == "RGB":
            img = img.quantize(colors=config.colors, method=Image.MEDIANCUT)
        frames.append(img)

    duration_per_frame = round(1000 / config.fps)

    if config.duration_ms is not None:
        duration_per_frame = round(config.duration_ms / len(frames))

    frames[0].save(
        str(output),
        save_all=True,
        append_images=frames[1:],
        duration=duration_per_frame,
        loop=config.loop,
        optimize=config.optimize,
        comment=_build_gif_comment(config),
    )

    return output


def _assemble_mp4(
    frame_paths: Sequence[Path],
    output: Path,
    config: RenderConfig,
) -> Path:
    """Assemble frames into an MP4 using ffmpeg."""
    # Determine frame pattern
    build_dir = frame_paths[0].parent
    crf = _quality_to_crf(config.quality)

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(config.fps),
        "-i", str(build_dir / "frame_%04d.png"),
        "-c:v", "libx264",
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-metadata", f"comment=Generated by tikzgif",
        str(output),
    ]

    subprocess.run(cmd, check=True, capture_output=True)
    return output


def _assemble_webp(
    frame_paths: Sequence[Path],
    output: Path,
    config: RenderConfig,
) -> Path:
    """Assemble frames into an animated WebP using Pillow."""
    frames = [Image.open(p).convert("RGBA") for p in frame_paths]

    for i, img in enumerate(frames):
        if config.width or config.height:
            frames[i] = _resize(img, config.width, config.height)

    duration_per_frame = round(1000 / config.fps)

    frames[0].save(
        str(output),
        save_all=True,
        append_images=frames[1:],
        duration=duration_per_frame,
        loop=config.loop,
        quality=config.quality,
    )

    return output


def _assemble_apng(
    frame_paths: Sequence[Path],
    output: Path,
    config: RenderConfig,
) -> Path:
    """Assemble frames into an APNG using Pillow."""
    frames = [Image.open(p).convert("RGBA") for p in frame_paths]

    for i, img in enumerate(frames):
        if config.width or config.height:
            frames[i] = _resize(img, config.width, config.height)

    duration_per_frame = round(1000 / config.fps)

    frames[0].save(
        str(output),
        save_all=True,
        append_images=frames[1:],
        duration=duration_per_frame,
        loop=config.loop,
    )

    return output


def _resize(
    img: Image.Image,
    width: int | None,
    height: int | None,
) -> Image.Image:
    """Resize preserving aspect ratio."""
    orig_w, orig_h = img.size
    if width and not height:
        height = round(orig_h * width / orig_w)
    elif height and not width:
        width = round(orig_w * height / orig_h)
    elif not width and not height:
        return img
    return img.resize((width, height), Image.LANCZOS)


def _quality_to_crf(quality: int) -> int:
    """Map quality (1-100) to ffmpeg CRF (51-0)."""
    return round(51 * (1 - quality / 100))


def _build_gif_comment(config: RenderConfig) -> str:
    """Build the GIF comment extension string."""
    lines = [
        "Generated by tikzgif",
        f"Source: {config.input_file.name}",
        f"Frames: {len(config.frame_specs())}",
        f"FPS: {config.fps}",
    ]
    for sweep in config.sweeps:
        lines.append(
            f"Parameter: {sweep.name}={sweep.start}:{sweep.end}:{sweep.steps}"
        )
    return "\n".join(lines)
```

### 4.9 Error Recovery and Partial Output

If some frames fail to compile:

1. tikzgif logs each failure with the LaTeX error output.
2. By default, the build **aborts** after the first failure.
3. With `--skip-errors` (or `skip_errors=True` in Python), tikzgif continues and assembles only the successful frames, logging a warning about gaps.
4. The manifest.json records `"status": "failed"` for broken frames with the error message.

```bash
# Continue past compilation errors
tikzgif --skip-errors -p t=0:10:200 fragile_sim.tex
# Output: "Warning: 3/200 frames failed. Output contains 197 frames."
```

---

## Appendix A: Complete CLI Help Text

```
$ tikzgif --help

Usage: tikzgif [OPTIONS] COMMAND [ARGS]...

  tikzgif -- Convert parameterized TikZ/LaTeX files into animated GIFs,
  MP4s, WebPs, or APNGs in a single command.

Options:
  --version   Show version and exit.
  -h, --help  Show this message and exit.

Commands:
  render   Compile a .tex file into an animated output (default).
  preview  Render and open in viewer or start HTTP preview server.
  watch    Re-render automatically when source files change.
  inspect  Parse a .tex file and show detected parameters.
  init     Create a tikzgif.toml config file in the current directory.
  clean    Remove intermediate build artifacts.
```

```
$ tikzgif render --help

Usage: tikzgif render [OPTIONS] INPUT

  Render a parameterized .tex file into an animated output.

  INPUT may be a .tex file, a .toml manifest, or a directory containing
  tikzgif.toml.

  Parameters can be specified via -p flags, magic comments in the .tex
  file, or a tikzgif.toml config file. CLI flags take highest precedence.

Animation Parameters:
  -p, --param TEXT         Parameter sweep: NAME=START:END:STEPS
                           May be repeated for multi-param animations.
  --sweep [product|zip|chain]
                           How to combine multiple parameter sweeps.
                           [default: product]

Output:
  -o, --output PATH        Output file path.
  -f, --format [gif|mp4|webp|apng]
                           Output format. [default: gif]
  --fps INTEGER            Frames per second. [default: 24]
  --loop INTEGER           Loop count (0=infinite). [default: 0]
  --duration INTEGER       Total duration in ms (overrides fps).

Rendering:
  --dpi INTEGER            Rasterization DPI. [default: 150]
  --density INTEGER        Alias for --dpi.
  --width INTEGER          Output width in pixels.
  --height INTEGER         Output height in pixels.
  --bg TEXT                Background color. [default: white]
  --quality INTEGER        Compression quality 1-100. [default: 85]
  --colors INTEGER         GIF palette size 2-256. [default: 256]
  --optimize / --no-optimize
                           GIF delta-frame optimization. [default: True]

LaTeX:
  --engine [pdflatex|lualatex|xelatex]
                           LaTeX engine. [default: pdflatex]
  --shell-escape           Pass --shell-escape to LaTeX.
  --tex-args TEXT          Extra LaTeX engine arguments.
  --preamble PATH          Additional preamble file to \input.

Build:
  -j, --jobs INTEGER       Parallel workers (0=auto). [default: 0]
  --keep-frames            Keep frame images after assembly.
  --build-dir PATH         Intermediate file directory.
                           [default: .tikzgif_build]
  --clean-before           Remove build dir before starting.
  --skip-errors            Continue past frame compilation failures.

Behavior:
  --dry-run                Show plan without executing.
  --force                  Overwrite output without prompting.
  -v, --verbose            Increase verbosity (repeat for more).
  -q, --quiet              Suppress all output except errors.
  --log PATH               Also log to this file.
  --progress / --no-progress
                           Show/hide progress bar.
  --config PATH            Config file path.
  --no-config              Ignore config files.

  -h, --help               Show this message and exit.
```

## Appendix B: Dependencies

```toml
# pyproject.toml [project.dependencies]
[project]
name = "tikzgif"
requires-python = ">=3.10"
dependencies = [
    "click>=8.1",
    "Pillow>=10.0",
    "pdf2image>=1.16",
    "tomli>=2.0; python_version < '3.11'",
    "rich>=13.0",
    "watchdog>=3.0",
]

[project.optional-dependencies]
mp4 = ["ffmpeg-python>=0.2"]   # ffmpeg must be installed separately
jupyter = ["ipywidgets>=8.0", "IPython>=8.0"]
dev = [
    "pytest>=7.0",
    "pytest-cov",
    "mypy>=1.5",
    "ruff>=0.1",
]

[project.scripts]
tikzgif = "tikzgif.cli:main"
```

## Appendix C: Error Types

```python
"""tikzgif exception hierarchy."""

class TikzGifError(Exception):
    """Base exception for all tikzgif errors."""

class LatexCompilationError(TikzGifError):
    """A LaTeX compilation failed.

    Attributes:
        frame_index: Which frame failed.
        log_output: The LaTeX log content.
        tex_path: Path to the .tex file that failed.
    """
    def __init__(
        self,
        message: str,
        frame_index: int,
        log_output: str,
        tex_path: str,
    ) -> None:
        super().__init__(message)
        self.frame_index = frame_index
        self.log_output = log_output
        self.tex_path = tex_path

class RasterizationError(TikzGifError):
    """PDF-to-image conversion failed."""

class AssemblyError(TikzGifError):
    """Frame assembly into output format failed."""

class ConfigError(TikzGifError):
    """Configuration file parsing or validation error."""

class ParameterError(TikzGifError):
    """Invalid parameter specification."""

class DependencyError(TikzGifError):
    """A required external tool is missing (pdflatex, ffmpeg, etc.)."""
```
