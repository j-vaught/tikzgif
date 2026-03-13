# tikzgif

Convert a parameterized TikZ/LaTeX file into an animation from one command.

`tikzgif` compiles frames in parallel and renders to GIF or MP4.

## Quick Examples

<p align="center">
  <img src="outputs/02_bouncing_ball.gif" alt="Bouncing ball" width="300"/>
  <img src="outputs/12_gear_train.gif" alt="Gear train" width="300"/>
</p>
<p align="center">
  <img src="outputs/09_em_wave.gif" alt="EM wave" width="300"/>
  <img src="outputs/30_wave_interference.gif" alt="Wave interference" width="300"/>
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

## More GIF Examples

See [EXAMPLES.md](EXAMPLES.md) for the full gallery.

<table>
<tr>
<td align="center" width="25%">
<img src="outputs/01_rotating_square.gif" alt="Rotating square" width="220"/><br/>
<b>Rotating Square</b>
</td>
<td align="center" width="25%">
<img src="outputs/03_sine_wave_phase.gif" alt="Sine wave phase" width="220"/><br/>
<b>Sine Wave Phase</b>
</td>
<td align="center" width="25%">
<img src="outputs/06a_bubble_sort.gif" alt="Bubble sort" width="220"/><br/>
<b>Bubble Sort</b>
</td>
<td align="center" width="25%">
<img src="outputs/07_mandelbrot_zoom.gif" alt="Mandelbrot zoom" width="220"/><br/>
<b>Mandelbrot Zoom</b>
</td>
</tr>
<tr>
<td align="center" width="25%">
<img src="outputs/08_step_response.gif" alt="Step response" width="220"/><br/>
<b>Step Response</b>
</td>
<td align="center" width="25%">
<img src="outputs/10_rc_circuit.gif" alt="RC circuit" width="220"/><br/>
<b>RC Circuit</b>
</td>
<td align="center" width="25%">
<img src="outputs/11_pendulum.gif" alt="Pendulum" width="220"/><br/>
<b>Pendulum</b>
</td>
<td align="center" width="25%">
<img src="outputs/14_heat_equation.gif" alt="Heat equation" width="220"/><br/>
<b>Heat Equation</b>
</td>
</tr>
<tr>
<td align="center" width="25%">
<img src="outputs/16_antenna_radiation.gif" alt="Antenna radiation" width="220"/><br/>
<b>Antenna Radiation</b>
</td>
<td align="center" width="25%">
<img src="outputs/17_bode_plot.gif" alt="Bode plot" width="220"/><br/>
<b>Bode Plot</b>
</td>
<td align="center" width="25%">
<img src="outputs/21_fourier_series.gif" alt="Fourier series" width="220"/><br/>
<b>Fourier Series</b>
</td>
<td align="center" width="25%">
<img src="outputs/31_four_bar_linkage.gif" alt="Four-bar linkage" width="220"/><br/>
<b>Four-Bar Linkage</b>
</td>
</tr>
</table>

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
