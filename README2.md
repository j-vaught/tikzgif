# tikzgif

Convert a parameterized TikZ/LaTeX file into an animation from one command.

`tikzgif` compiles frames in parallel, auto-detects bounding boxes, and renders to formats like GIF, MP4, WebP, and APNG.

## Quick Examples

<p align="center">
  <img src="outputs/02_bouncing_ball.gif" alt="Bouncing ball" width="300"/>
  <img src="outputs/12_gear_train.gif" alt="Gear train" width="300"/>
</p>
<p align="center">
  <img src="outputs/09_em_wave.gif" alt="EM wave" width="300"/>
  <img src="outputs/30_wave_interference.gif" alt="Wave interference" width="300"/>
</p>

## Install (from source)

`tikzgif` is not yet published as a `pip install tikzgif` package on PyPI.

Install from this repository instead.

```bash
git clone https://github.com/j-vaught/tikzgif.git
cd tikzgif
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Basic Usage

1. Put `\PARAM` where you want the animated value.
2. Render frames by sweeping a range.

```bash
tikzgif render examples/02_bouncing_ball.tex \
  --frames 60 \
  --start 0 \
  --end 1 \
  --fps 30 \
  -o outputs/bouncing_ball.gif
```

## Minimal TikZ Pattern

```tex
% Use \PARAM anywhere you want the animated value
\\draw[thick] (0,0) circle ({0.5 + 0.2*\\PARAM});
```

## Common Output Targets

- GIF for docs and slides.
- MP4 for video workflows.
- WebP/APNG for web pages.

## Requirements

- A LaTeX engine available on `PATH` (`pdflatex`, `xelatex`, or `lualatex`).
- Python 3.10+.

