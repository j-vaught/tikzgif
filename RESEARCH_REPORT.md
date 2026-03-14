# Tools for Converting LaTeX TikZ to Animations

**Date:** 2026-03-13
**Author:** J.C. Vaught

---

## Executive Summary

This report surveys the landscape of tools, packages, and workflows that convert LaTeX TikZ code into animations (GIFs, videos, SVG animations). The research spans dedicated CLI tools, LaTeX-native packages, JavaScript/Node.js renderers, Python libraries, and community-developed pipelines. No single dominant, well-maintained, feature-rich tool exists for this task. The space is fragmented, with most solutions being either (a) LaTeX packages that embed animations inside PDFs with severe viewer restrictions, (b) small GitHub repositories with minimal maintenance, or (c) manual multi-step shell pipelines. The `tikzgif` project fills a genuine gap as the only dedicated, pip-installable Python CLI that automates the full parameterized TikZ-to-GIF pipeline with parallel compilation, content-addressable caching, and pluggable backends.

### Opportunities

- **SVG animation output** from frame-by-frame tools (using APNG or animated SVG assembly) would preserve vector quality while being universally viewable.
- **Cloud/CI integration** (GitHub Actions, Docker containers) for rendering TikZ animations is largely undeveloped.

---

## Appendix A: Example Gallery Repositories

| Repository | URL | Description | Stars |
|------------|-----|-------------|-------|
| takidau/animations | https://github.com/takidau/animations | LaTeX/TikZ animation collection (streaming data viz). 47 commits, 418 files. CC-BY-SA-4.0. | -- |
| stevenktruong/math-animations | https://github.com/stevenktruong/math-animations | Math animations in TikZ with web preview. Uses ffmpeg for GIF. | -- |
| 2b-t/latex-tikz-examples | https://github.com/2b-t/latex-tikz-examples | Makefile-based (latexmk). Docker/Docker-Compose support. Uses `animate` package. | 10 |
| Jubeku/TIKZ_animate | https://github.com/Jubeku/TIKZ_animate | TikZ `animate` package demonstrations (seismic wave splitting) | 0 |
| srush/beamer-animation | https://github.com/srush/beamer-animation | Beamer + TikZ animation templates with `\uncover` | -- |
| Pseudonym321/LaTeX_Repository | https://github.com/Pseudonym321/LaTeX_Repository | TikZ illustrations and animations | -- |

## Appendix B: Key External Dependencies

| Tool | Purpose | Used By |
|------|---------|---------|
| **ImageMagick** (`magick`/`convert`) | PDF to GIF conversion, rasterization | TikZ2animation, vTikZ, manual pipeline, tikzgif (fallback) |
| **ffmpeg** | Video assembly (MP4), advanced GIF creation | vTikZ, A-LaTeX-PGF-TikZ-Animation, tikzgif |
| **Ghostscript** (`gs`) | PDF rasterization, bounding box extraction | tikzgif, manual pipeline |
| **pdftoppm** (poppler-utils) | PDF to PNG conversion | tikzgif (default), manual pipeline |
| **Gifsicle** | GIF optimization | Manual pipeline (optional) |
| **dvisvgm** | DVI/PDF to SVG conversion | TikZ animations lib, animate (SVG mode) |
| **PyMuPDF** (`fitz`) | Pure Python PDF rendering | tikzgif (fallback backend) |
| **Pillow** | Image processing, GIF assembly | tikzgif |

