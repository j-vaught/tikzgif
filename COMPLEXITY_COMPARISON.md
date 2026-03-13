# tikzgif Complexity Comparison

This document compares the current trimmed codebase to a proposed super-lite version.

## Current State Summary

Branch used for this analysis.

- `trim-basics-core`

Current intent.

- Keep robust render behavior.
- Remove template and alternate pipeline subsystems.

What has already been removed on this branch.

- `tikzgif/cli/templates_cli.py`
- `tikzgif/template_registry.py`
- `tikzgif/template_schema.py`
- `tikzgif/frames.py`
- `tikzgif/processing.py`
- `tikzgif/config.py`

## What Is Actually Implemented and Active Now

Primary runtime path.

1. CLI entrypoint in `tikzgif/cli/main.py`.
2. `render` command in `tikzgif/cli/render_cli.py`.
3. Frame compilation and bbox workflow in `tikzgif/compiler.py` and `tikzgif/tex_gen.py`.
4. PDF-to-image backend selection in `tikzgif/detection.py` and `tikzgif/backends.py`.
5. Animation assembly in `tikzgif/assembly.py`.

Still-active feature set.

- Parameter sweep rendering.
- Two-pass bounding-box normalization.
- Frame caching.
- Error policy handling (`abort`, `skip`, `retry`).
- Multiple LaTeX engines (`pdflatex`, `xelatex`, `lualatex`).
- Multiple output formats exposed by CLI (`gif`, `mp4`, `webp`, `apng`, `svg`).
- Multiple PDF conversion backend fallbacks.

## Complexity Drivers in Current Code

The following modules carry most of the remaining complexity.

- `tikzgif/assembly.py`.
- `tikzgif/backends.py`.
- `tikzgif/compiler.py`.

Why these are complex.

- `assembly.py` supports multiple output formats and encoding pathways.
- `backends.py` supports multiple converter engines and detection fallbacks.
- `compiler.py` supports multi-process compile orchestration, retries, cache integration, and two-pass bbox logic.

## Proposed Super-Lite Target

Goal.

- Minimize cognitive load and moving parts.
- Keep only the workflow needed for basic TikZ to GIF rendering.

Super-lite feature scope.

- One command. `render`.
- One output format. `gif`.
- One PDF conversion backend. `pdftoppm`.
- One compile mode. Single pass.
- Minimal CLI arguments only.

Recommended minimal CLI arguments.

- Positional input `.tex` file.
- `--start`.
- `--end`.
- `--frames`.
- `--fps`.
- `-o/--output`.

Optional minimal extras if desired.

- `--workers`.
- `--engine`.

## Side-by-Side Comparison

| Area | Current `trim-basics-core` | Super-lite target |
|---|---|---|
| CLI commands | `render` | `render` |
| Output formats | `gif`, `mp4`, `webp`, `apng`, `svg` | `gif` only |
| Assembly logic | Multi-format assemblers | Single GIF assembler |
| PDF raster backends | Auto-detect fallback chain | `pdftoppm` only |
| Compile strategy | Two-pass bbox normalization | Single-pass compile |
| Error handling | Retry/skip/abort policy | Fail-fast or simple retry |
| Caching | Content-addressable frame cache | Optional keep or remove |
| Engine support | `pdflatex`, `xelatex`, `lualatex` | Optional reduce to one |
| Config surface | Large | Small |
| Code volume | Medium-high | Low |

## Behavioral Tradeoffs

What you gain with super-lite.

- Faster onboarding for new maintainers.
- Lower bug surface.
- Easier local debugging.
- Easier to audit and review.

What you give up with super-lite.

- Fewer output targets.
- Less resilience on diverse machine setups.
- Potential frame jitter if two-pass bbox logic is removed.
- Less flexibility for edge-case LaTeX/render workflows.

## Recommendation

If your priority is maintainability and predictable local use, super-lite is a good next step.

If your priority is broad compatibility and feature breadth, the current `trim-basics-core` strikes a middle ground.

Practical path.

1. Keep `trim-basics-core` as the stable branch.
2. Create `trim-super-lite` as an experiment branch.
3. Freeze acceptance criteria before refactor.
4. Validate with canonical examples, such as `examples/06b_selection_sort.tex`.

## Validation Baseline Example

A useful baseline comparison command for this repository.

```bash
PYTHONPATH=. python3 /tmp/tikzgif_runner.py render examples/06b_selection_sort.tex \
  --start 0 --end 5 --frames 40 --fps 20 --format gif --workers 1 \
  -o /tmp/tikzgif_compare/06b_40f_20fps_0to5.gif
```

This setting covers the full `\PARAM` range used by `06b` and is suitable for output parity checks across branches.
