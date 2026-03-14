# tikzgif

Convert a parameterized TikZ/LaTeX file into an animation from one command.

`tikzgif` compiles frames in parallel and renders to GIF or MP4.

## Quick Examples

<p align="center">
  <img src="outputs/mechanical/01_bouncing_ball.gif" alt="Bouncing ball" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/mechanical/03_gear_train.gif" alt="Gear train" width="380"/>
</p>

<p align="center">
  <img src="outputs/electromagnetic/03_em_wave_3d.gif" alt="EM wave" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/geometry/04_wave_interference.gif" alt="Wave interference" width="380"/>
</p>

## Why tikzgif?

| | **tikzgif** | [TikZ2animation](https://github.com/heschmann/TikZ2animation) |
|---|---|---|
| Automation | One command from `.tex` to animation output | Manual script workflow |
| Parallelism | Frame compilation across CPU cores | Sequential compilation |
| Output formats | GIF, MP4 | GIF only |
| LaTeX engines | `pdflatex`, `xelatex`, `lualatex` | `pdflatex` only |
| Caching | Content-addressable cache for unchanged frames | None |
| Installation | Install from source (`pip install -e .`) | Clone repo + ImageMagick setup |

## Install (from source)

```bash
git clone https://github.com/j-vaught/tikzgif.git
cd tikzgif
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Quickstart

One command from `.tex` to `.gif`:

```bash
tikzgif render examples/mechanical/01_bouncing_ball.tex --output ball.gif
```

That's it. Put `\PARAM` in any TikZ file where you want the animated value, and tikzgif sweeps the range across frames.

## Gallery Preview

See [EXAMPLES.md](EXAMPLES.md) for the full gallery with all 31 examples.

<p align="center">
  <img src="outputs/geometry/02_mandelbrot_zoom.gif" alt="Mandelbrot zoom" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/computers/02a_bubble_sort.gif" alt="Bubble sort" width="380"/>
</p>

<p align="center">
  <img src="outputs/signal_processing/01_fourier_series.gif" alt="Fourier series" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/mechanical/04_four_bar_linkage.gif" alt="Four-bar linkage" width="380"/>
</p>

## Minimal TikZ Pattern

```tex
% Use \PARAM anywhere you want the animated value
\\draw[thick] (0,0) circle ({0.5 + 0.2*\\PARAM});
```

## Common Output Targets

- GIF for docs and slides.
- MP4 for video workflows.

## Requirements

- A LaTeX engine available on `PATH` (`pdflatex`, `xelatex`, or `lualatex`).
- Python 3.10+.
- `pdftoppm` from poppler-utils for PDF to PNG conversion.
- `ffmpeg` only when writing MP4 output.
