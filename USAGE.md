# Usage Guide

This guide covers everything you need to know to use tikzgif, from writing your first animated TikZ template to tuning output quality and performance.

Note from author -- THIS WAS WRITTEN BY CLAUDE AND HAD NOT BEEN VERIFIED AS OF YET. Proceed with Caution...

## Table of Contents

- [Usage Guide](#usage-guide)
  - [Table of Contents](#table-of-contents)
  - [How tikzgif Works](#how-tikzgif-works)
  - [Writing a Template](#writing-a-template)
    - [Minimal Template](#minimal-template)
    - [Template Structure](#template-structure)
    - [Mapping the Parameter Range](#mapping-the-parameter-range)
    - [Using a Custom Token Name](#using-a-custom-token-name)
  - [Basic Rendering](#basic-rendering)
  - [Command Reference](#command-reference)
    - [tikzgif render](#tikzgif-render)
      - [Parameter Sweep Options](#parameter-sweep-options)
      - [Output Options](#output-options)
      - [LaTeX Options](#latex-options)
      - [Compilation Options](#compilation-options)
      - [Cache Options](#cache-options)
      - [Rasterization Options](#rasterization-options)
      - [GIF Options](#gif-options)
      - [MP4 Options](#mp4-options)
      - [Frame Timing Options](#frame-timing-options)
      - [Metadata Options](#metadata-options)
      - [Diagnostic Options](#diagnostic-options)
    - [tikzgif inspect](#tikzgif-inspect)
  - [Parameter Sweep](#parameter-sweep)
  - [LaTeX Engine Selection](#latex-engine-selection)
  - [Bounding Boxes](#bounding-boxes)
    - [Recommended approach: `\useasboundingbox` in your template](#recommended-approach-useasboundingbox-in-your-template)
    - [Alternative: `--bbox` flag](#alternative---bbox-flag)
    - [Figuring out the right bounding box](#figuring-out-the-right-bounding-box)
  - [Output Formats](#output-formats)
    - [GIF (default)](#gif-default)
    - [MP4](#mp4)
  - [Quality and Resolution](#quality-and-resolution)
  - [Rasterization Backends](#rasterization-backends)
  - [Caching](#caching)
  - [Performance Tuning](#performance-tuning)
    - [Parallel compilation](#parallel-compilation)
    - [Frame count](#frame-count)
    - [Timeout](#timeout)
    - [Rasterization threads](#rasterization-threads)
  - [Error Handling](#error-handling)
  - [Test Mode](#test-mode)
  - [Exporting Raw Frames](#exporting-raw-frames)
  - [Frame Timing](#frame-timing)
  - [Metadata](#metadata)
  - [Anti-Aliasing](#anti-aliasing)
  - [Transparency](#transparency)
  - [Troubleshooting](#troubleshooting)
    - ["No \\PARAM token found"](#no-param-token-found)
    - [Jittery animation](#jittery-animation)
    - [Frames timing out](#frames-timing-out)
    - [Wrong LaTeX engine selected](#wrong-latex-engine-selected)
    - [Missing packages](#missing-packages)
    - [Large GIF file sizes](#large-gif-file-sizes)
    - [Check your environment](#check-your-environment)

---

## How tikzgif Works

tikzgif converts a parameterized TikZ `.tex` file into an animated GIF or MP4. The pipeline has four stages.

1. **Template parsing.** tikzgif reads your `.tex` file and locates the `\PARAM` token (or a custom token you specify). It validates the template structure and detects which LaTeX engine and packages are needed.

2. **Frame generation and compilation.** tikzgif generates linearly-spaced parameter values from `--start` to `--end` across `--frames` steps. For each value, it substitutes `\PARAM` with that number, wraps the result in a `standalone` document, and compiles it to PDF. Compilation runs in parallel across your CPU cores.

3. **PDF rasterization.** Each per-frame PDF is converted to a PNG image at the specified DPI using `pdftoppm` (or another backend).

4. **Animation assembly.** The PNG frames are assembled into a GIF (using a custom global-palette algorithm) or an MP4 (using ffmpeg).

The entire pipeline runs from a single command.

---

## Writing a Template

A tikzgif template is a standard LaTeX file that uses the `standalone` document class. The only special requirement is the `\PARAM` token, which tikzgif replaces with a numeric value for each frame.

### Minimal Template

```tex
\documentclass[tikz]{standalone}
\begin{document}
\begin{tikzpicture}
  \pgfmathsetmacro{\angle}{\PARAM * 360}
  \draw[thick, rotate=\angle] (-1,-1) rectangle (1,1);
\end{tikzpicture}
\end{document}
```

When rendered with the default `--start 0 --end 1`, tikzgif generates 90 frames where `\PARAM` takes values from 0.0 to 1.0. In this example, the expression `\PARAM * 360` maps that range to 0-360 degrees of rotation.

### Template Structure

Every template must have these elements.

**Document class.** Use `standalone` with the `tikz` option. tikzgif wraps each frame in `standalone` internally, so your template should already use it.

```tex
\documentclass[tikz]{standalone}
```

If you use `pgfplots` without TikZ features directly, you can use `\documentclass[border=5pt]{standalone}` instead.

**The `\PARAM` token.** Place `\PARAM` anywhere in the body of your document (between `\begin{document}` and `\end{document}`) where you want the animated value. It must appear at least once. You can use it multiple times and inside any math expression.

```tex
\pgfmathsetmacro{\radius}{0.5 + 2.0 * \PARAM}
\pgfmathsetmacro{\opacity}{\PARAM}
\draw[fill=blue, opacity=\opacity] (0,0) circle (\radius);
```

**Packages.** Include any LaTeX packages you need with `\usepackage{}`. tikzgif detects packages automatically and selects the appropriate LaTeX engine.

### Mapping the Parameter Range

`\PARAM` always receives a raw numeric value between `--start` and `--end` (default: 0 to 1). To map this to a different range, use `\pgfmathsetmacro` at the top of your `tikzpicture`.

Map 0-1 to 0-360 degrees:
```tex
\pgfmathsetmacro{\angle}{\PARAM * 360}
```

Map 0-1 to an exponent range of 0.3-5.0:
```tex
\pgfmathsetmacro{\nval}{\PARAM * 4.7 + 0.3}
```

Map 0-1 to a time span of 0-2.838 seconds:
```tex
\pgfmathsetmacro{\tval}{\PARAM * 2.838}
```

You can also set `--start` and `--end` directly to the range you need and use `\PARAM` as-is.

### Using a Custom Token Name

If `\PARAM` conflicts with something in your document, use `--param` to set a different token name.

```bash
tikzgif render my_file.tex --param SWEEP
```

Your `.tex` file would then use `\SWEEP` instead of `\PARAM`.

---

## Basic Rendering

The simplest possible command:

```bash
tikzgif render my_template.tex
```

This compiles 90 frames with `\PARAM` sweeping from 0 to 1, and writes the output as a GIF. The output filename is derived from the input filename (e.g., `my_template.gif`).

Specify an output path:

```bash
tikzgif render my_template.tex -o output.gif
```

---

## Command Reference

tikzgif has two subcommands: `render` and `inspect`.

### tikzgif render

```
tikzgif render <tex_file> [options]
```

`<tex_file>` is the only required argument. Everything else is optional.

#### Parameter Sweep Options

| Flag | Default | Description |
|------|---------|-------------|
| `--param TOKEN` | `PARAM` | Token name to substitute (without the backslash). Your `.tex` file uses `\TOKEN`. |
| `--start VALUE` | `0.0` | Starting parameter value. |
| `--end VALUE` | `1.0` | Ending parameter value. |
| `--frames N` | `90` | Number of animation frames to generate. More frames = smoother animation but longer compile time. |

#### Output Options

| Flag | Default | Description |
|------|---------|-------------|
| `-o, --output PATH` | auto | Output file path. If omitted, derived from the input filename with the appropriate extension. |
| `--format gif\|mp4` | `gif` | Output animation format. MP4 requires `ffmpeg`. |
| `--fps N` | `30` | Frames per second in the output animation. |
| `--quality web\|presentation\|print` | `presentation` | Quality preset controlling the maximum output width: `web` = 800px, `presentation` = 1920px, `print` = 3840px. |
| `--dpi N` | `300` | DPI for PDF-to-PNG rasterization. Higher values produce sharper output but larger files. |

#### LaTeX Options

| Flag | Default | Description |
|------|---------|-------------|
| `--engine pdflatex\|xelatex\|lualatex` | auto | LaTeX engine. By default, tikzgif auto-detects based on your packages (see [LaTeX Engine Selection](#latex-engine-selection)). |
| `--shell-escape` | off | Pass `--shell-escape` to the LaTeX engine. Required by packages like `minted`, `pythontex`, and `svg`. tikzgif warns if it detects these packages without this flag. |
| `--latex-arg ARG` | none | Extra argument forwarded to the LaTeX engine. Can be repeated for multiple arguments: `--latex-arg "-synctex=1" --latex-arg "-file-line-error"`. |
| `--bbox xmin,ymin,xmax,ymax` | none | Enforce a fixed bounding box across all frames by injecting `\useasboundingbox`. Coordinates are in TikZ units (cm by default). See [Bounding Boxes](#bounding-boxes). |

#### Compilation Options

| Flag | Default | Description |
|------|---------|-------------|
| `--workers N` | auto | Number of parallel compilation workers. Default is `cpu_count - 1`. Set to 1 for sequential compilation. |
| `--timeout SECONDS` | `30.0` | Maximum time in seconds for compiling a single frame. Increase for complex frames. Set to 0 for no timeout. |
| `--error-policy abort\|skip\|retry` | `retry` | How to handle frame compilation failures. See [Error Handling](#error-handling). |

#### Cache Options

| Flag | Default | Description |
|------|---------|-------------|
| `--cache-dir PATH` | platform default | Custom directory for the compilation cache. Defaults to `~/.cache/tikzgif` on Linux/macOS. |
| `--no-cache` | off | Disable the compilation cache entirely. Every frame recompiles from scratch. |

#### Rasterization Options

| Flag | Default | Description |
|------|---------|-------------|
| `--backend NAME` | `pdftoppm` | Raster backend for PDF-to-PNG conversion. See [Rasterization Backends](#rasterization-backends). |
| `--color-space rgb\|rgba\|grayscale` | `rgba` | Color space for rasterized images. Use `rgba` if you need transparency support. |
| `--background COLOR` | `white` | Background color for rasterized images. Set to `none` for transparent backgrounds (requires `rgba` color space). |
| `--antialias` | off | Enable supersampled anti-aliasing. Renders at a higher internal resolution and downscales. |
| `--antialias-factor N` | `2` | Supersampling multiplier when `--antialias` is enabled. A factor of 2 renders at 2x resolution. |
| `--raster-threads N` | `1` | Number of threads for rasterization. |

#### GIF Options

| Flag | Default | Description |
|------|---------|-------------|
| `--gif-loop N` | `0` | Number of times the GIF loops. 0 = loop forever. |

#### MP4 Options

| Flag | Default | Description |
|------|---------|-------------|
| `--mp4-crf N` | `23` | Constant Rate Factor for MP4 encoding. Lower = higher quality, larger file. Range: 0-51. |
| `--mp4-preset NAME` | `medium` | ffmpeg encoding preset. Options include `ultrafast`, `fast`, `medium`, `slow`, `veryslow`. Slower presets produce smaller files. |
| `--mp4-pix-fmt FORMAT` | `yuv420p` | Pixel format for MP4 output. `yuv420p` is the most compatible. |

#### Frame Timing Options

| Flag | Default | Description |
|------|---------|-------------|
| `--frame-delay-ms N` | from fps | Override the default delay between frames in milliseconds. If not set, calculated from `--fps`. |
| `--pause-first-ms N` | none | Add extra pause on the first frame, in milliseconds. |
| `--pause-last-ms N` | none | Add extra pause on the last frame, in milliseconds. |

#### Metadata Options

| Flag | Default | Description |
|------|---------|-------------|
| `--title TEXT` | empty | Title metadata embedded in the output file. |
| `--author TEXT` | empty | Author metadata embedded in the output file. |
| `--comment TEXT` | `Generated by tikzgif` | Comment metadata embedded in the output file. |

#### Diagnostic Options

| Flag | Default | Description |
|------|---------|-------------|
| `--test` | off | Render only the first and last frames as standalone PNG files. Useful for quick visual checks before committing to a full render. |
| `--raw-pdf-dir PATH` | none | Export all per-frame PDFs to this directory. |
| `--raw-png-dir PATH` | none | Export all per-frame PNGs to this directory. |

### tikzgif inspect

Diagnostic subcommand for checking your environment and templates.

**List available LaTeX engines:**
```bash
tikzgif inspect engines
```
Prints each engine name and its path, or `missing` if not found.

**List available raster backends:**
```bash
tikzgif inspect backends
```
Prints each backend name and whether it is available on your system.

**Inspect a template:**
```bash
tikzgif inspect template my_file.tex
```
Prints parsed metadata: document class, class options, detected packages, whether a bounding box is present, whether `--shell-escape` is needed, and the parameter token. Accepts `--param TOKEN` to check for a custom token name.

---

## Parameter Sweep

tikzgif generates parameter values as a linearly-spaced sequence from `--start` to `--end` with `--frames` total values (inclusive of both endpoints).

```bash
# 60 frames, parameter goes from 0.0 to 1.0
tikzgif render template.tex --frames 60

# 120 frames, parameter goes from -3.14 to 3.14
tikzgif render template.tex --start -3.14 --end 3.14 --frames 120
```

Each frame gets exactly one parameter value. Frame 0 gets `--start`, the last frame gets `--end`, and all frames in between are evenly spaced.

For non-linear sweeps (logarithmic, exponential, etc.), use `pgfmath` inside your template to transform the linear parameter.

```tex
% Logarithmic zoom: map linear 0-1 to exponential scale
\pgfmathsetmacro{\zoom}{10^(\PARAM * 3)}

% Ease-in-out: smooth start and stop
\pgfmathsetmacro{\t}{0.5 - 0.5 * cos(deg(\PARAM * 3.14159))}
```

---

## LaTeX Engine Selection

tikzgif supports three LaTeX engines: `pdflatex`, `xelatex`, and `lualatex`.

By default, tikzgif auto-detects the engine by scanning your template's preamble for packages.

| Detected package | Selected engine |
|---|---|
| `luacode`, `luatexbase`, `tikz-feynman` | `lualatex` |
| `fontspec`, `unicode-math` | `xelatex` (or `lualatex`) |
| Everything else | `pdflatex` |

To override auto-detection:

```bash
tikzgif render template.tex --engine lualatex
```

This is useful if your template uses engine-specific features that tikzgif does not detect automatically, or if you want to force a specific engine for compatibility.

---

## Bounding Boxes

Consistent bounding boxes across all frames are important for smooth animations. If the drawn content changes size from frame to frame (which is common), the output frames will have different dimensions and the animation will appear to jitter.

### Recommended approach: `\useasboundingbox` in your template

The most reliable way to fix the bounding box is to add `\useasboundingbox` inside your `tikzpicture`, before any drawing commands. This tells TikZ to use exactly this rectangle as the image boundary, regardless of what is drawn.

```tex
\begin{tikzpicture}
  \useasboundingbox (-5,-5) rectangle (5,5);
  % ... drawing commands ...
\end{tikzpicture}
```

Choose coordinates that fully enclose your drawing at every parameter value.

### Alternative: `--bbox` flag

If you do not want to modify your `.tex` file, use the `--bbox` flag. tikzgif injects the bounding box for you.

```bash
tikzgif render template.tex --bbox "-5,-5,5,5"
```

The format is `xmin,ymin,xmax,ymax` in TikZ units (centimeters by default). tikzgif inserts `\pgfresetboundingbox` followed by `\useasboundingbox` before `\end{tikzpicture}` in each frame.

If your template already contains `\useasboundingbox`, tikzgif will not inject a duplicate. In that case, the `--bbox` flag has no effect.

### Figuring out the right bounding box

Use `--test` to render only the first and last frames as PNGs, then check if the content fits within your bounding box at both extremes.

```bash
tikzgif render template.tex --test --bbox "-4,-4,4,4"
```

---

## Output Formats

### GIF (default)

```bash
tikzgif render template.tex --format gif
```

tikzgif uses a custom global-palette algorithm for GIF output. It scans color frequencies across all frames, picks the 256 most common colors, and maps remaining colors to their nearest neighbor. This produces smoother animations with less color banding than per-frame quantization.

The `--gif-loop` flag controls how many times the animation loops. The default of 0 means infinite looping.

### MP4

```bash
tikzgif render template.tex --format mp4
```

MP4 output requires `ffmpeg` on your PATH. The output uses H.264 encoding with configurable quality settings.

Lower `--mp4-crf` values produce higher quality at larger file sizes. The default of 23 is a good balance. For near-lossless quality, use `--mp4-crf 18`. For smaller files, try `--mp4-crf 28`.

The `--mp4-preset` flag trades encoding speed for file size. `ultrafast` encodes quickly but produces larger files. `veryslow` takes longer but produces the smallest files. The default `medium` is a reasonable middle ground.

---

## Quality and Resolution

Output resolution is controlled by three settings that interact.

**`--dpi`** (default: 300) controls the rasterization resolution when converting each PDF frame to PNG. Higher DPI produces sharper images.

**`--quality`** (default: `presentation`) applies a maximum width cap and downscales using Lanczos filtering if needed.

| Preset | Max width |
|--------|-----------|
| `web` | 800 px |
| `presentation` | 1920 px |
| `print` | 3840 px |

For example, with `--dpi 300` and `--quality web`, frames are rendered at 300 DPI and then downscaled so the output width does not exceed 800 pixels.

For the sharpest output, increase `--dpi`. For smaller file sizes, use a lower quality preset.

```bash
# High-quality for a presentation
tikzgif render template.tex --dpi 300 --quality presentation

# Small file for embedding on a website
tikzgif render template.tex --dpi 150 --quality web

# Maximum quality for print
tikzgif render template.tex --dpi 600 --quality print
```

---

## Rasterization Backends

tikzgif supports five backends for converting PDFs to PNGs. The `--backend` flag selects which one to use.

| Backend | Flag value | Requirements | Notes |
|---------|-----------|--------------|-------|
| pdftoppm | `pdftoppm` | `pdftoppm` binary (from poppler-utils) | Default. Fastest option. |
| PyMuPDF | `pymupdf` | `pip install pymupdf` | Pure Python, no external binaries needed. |
| pdf2image | `pdf2image` | `pip install pdf2image` + poppler | Python wrapper around poppler. |
| Ghostscript | `ghostscript` | `gs` binary | Widely available. |
| ImageMagick | `imagemagick` | `convert` binary | Slowest, but universally available. |

Check which backends are available on your system:

```bash
tikzgif inspect backends
```

---

## Caching

tikzgif uses a content-addressable cache to avoid recompiling unchanged frames. Each frame's complete `.tex` source is SHA-256 hashed, and the compiled PDF is stored under that hash. If you re-render the same template with the same parameters, cached frames are reused instantly.

The cache is stored at `~/.cache/tikzgif` on Linux/macOS and `%LOCALAPPDATA%\tikzgif` on Windows.

**Disable caching** for a single run:
```bash
tikzgif render template.tex --no-cache
```

**Use a custom cache directory:**
```bash
tikzgif render template.tex --cache-dir /tmp/my-cache
```

Caching is especially useful when iterating on a template. If you change the bounding box but not the drawing commands, most frames will still be cache hits.

---

## Performance Tuning

### Parallel compilation

By default, tikzgif compiles frames in parallel using `cpu_count - 1` workers. You can override this.

```bash
# Use 4 workers
tikzgif render template.tex --workers 4

# Sequential (single worker, useful for debugging)
tikzgif render template.tex --workers 1
```

### Frame count

Fewer frames means faster rendering. For a quick draft, try 30 frames. For a smooth final output, use 90-120.

```bash
tikzgif render template.tex --frames 30  # quick draft
tikzgif render template.tex --frames 120 # smooth
```

### Timeout

Complex frames (especially those using Lua computation or high-resolution plots) may take longer than the default 30-second timeout. Increase it or disable it.

```bash
tikzgif render template.tex --timeout 120   # 2-minute timeout
tikzgif render template.tex --timeout 0     # no timeout
```

### Rasterization threads

If rasterization is a bottleneck (uncommon), increase the thread count.

```bash
tikzgif render template.tex --raster-threads 4
```

---

## Error Handling

The `--error-policy` flag controls what happens when a frame fails to compile.

| Policy | Behavior |
|--------|----------|
| `retry` (default) | Retry the failed frame once with doubled timeout. If it fails again, skip it and continue. |
| `skip` | Skip the failed frame and continue with remaining frames. |
| `abort` | Stop the entire render immediately on the first failure. |

```bash
# Stop on first error (good for debugging templates)
tikzgif render template.tex --error-policy abort

# Skip failures silently
tikzgif render template.tex --error-policy skip
```

When frames fail, tikzgif prints a summary of which frames failed and why.

---

## Test Mode

Test mode renders only the first and last frames as standalone PNG files. This is the fastest way to check that your template works and that your bounding box is correct before committing to a full render.

```bash
tikzgif render template.tex --test
```

Output is two PNG files (one for `--start`, one for `--end`) printed to the console. No GIF or MP4 is produced.

Combine with `--bbox` to iterate on bounding box dimensions quickly.

```bash
tikzgif render template.tex --test --bbox "-5,-6,5,3"
```

---

## Exporting Raw Frames

You can export the intermediate per-frame PDFs or PNGs to a directory for inspection or use in other tools.

```bash
# Export all per-frame PDFs
tikzgif render template.tex --raw-pdf-dir ./pdfs

# Export all per-frame PNGs
tikzgif render template.tex --raw-png-dir ./pngs

# Both at once
tikzgif render template.tex --raw-pdf-dir ./pdfs --raw-png-dir ./pngs
```

The animation is still produced as normal. These flags add a copy step, they do not replace the animation output.

---

## Frame Timing

Frame timing defaults are calculated from `--fps`. At 30 fps, each frame displays for ~33 ms.

**Override the default delay between all frames:**
```bash
tikzgif render template.tex --frame-delay-ms 50   # 50ms per frame
```

**Pause on the first and/or last frame** for emphasis:
```bash
tikzgif render template.tex --pause-first-ms 500 --pause-last-ms 1000
```

This is useful for animations that should linger at the start or end state before looping.

---

## Metadata

Embed metadata in the output file:

```bash
tikzgif render template.tex \
  --title "Rotating Square" \
  --author "J.C. Vaught" \
  --comment "Parameter sweep from 0 to 360 degrees"
```

All three flags are optional. The `--comment` field defaults to `Generated by tikzgif`.

---

## Anti-Aliasing

Enable supersampled anti-aliasing for smoother edges:

```bash
tikzgif render template.tex --antialias
```

This renders at a higher internal resolution (controlled by `--antialias-factor`) and downscales with Lanczos filtering. The default factor of 2 renders at 2x resolution. Higher factors produce smoother results but increase rasterization time.

```bash
tikzgif render template.tex --antialias --antialias-factor 4
```

For most use cases, TikZ output at 300 DPI is already sharp and anti-aliasing is unnecessary.

---

## Transparency

To produce frames with transparent backgrounds:

```bash
tikzgif render template.tex --color-space rgba --background none
```

Both flags are needed. `--color-space rgba` enables the alpha channel, and `--background none` prevents filling the background with white.

Note that GIF only supports binary transparency (each pixel is fully transparent or fully opaque). For smooth transparency, use MP4 output with `--format mp4`.

---

## Troubleshooting

### "No \PARAM token found"

Your template must contain `\PARAM` (or your custom token) in the document body, between `\begin{document}` and `\end{document}`. Tokens in the preamble are not detected.

### Jittery animation

The drawn content is changing size across frames, causing each frame to have a different bounding box. Add `\useasboundingbox` to your template or use `--bbox`. See [Bounding Boxes](#bounding-boxes).

### Frames timing out

Increase the timeout or disable it:
```bash
tikzgif render template.tex --timeout 120
tikzgif render template.tex --timeout 0
```

### Wrong LaTeX engine selected

Override auto-detection:
```bash
tikzgif render template.tex --engine lualatex
```

### Missing packages

If LaTeX reports missing packages, install them through your TeX distribution (e.g., `tlmgr install pgfplots`). tikzgif does not manage LaTeX package installation.

### Large GIF file sizes

Reduce DPI, lower the quality preset, or decrease the frame count:
```bash
tikzgif render template.tex --dpi 150 --quality web --frames 45
```

### Check your environment

Run the inspect commands to verify that your LaTeX engines and raster backends are correctly installed:
```bash
tikzgif inspect engines
tikzgif inspect backends
```
