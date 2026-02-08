# From Static TikZ to Living Diagrams: Why I Built tikzgif

## 1. The Moment I Got Tired of Screenshot Workflows

I spent years making technical visuals in TikZ for lectures, reports, and demos. The drawings looked great as static figures, but the moment I wanted motion, everything broke down into a manual pipeline: tweak a parameter, compile, export, crop, repeat, stitch, tune quality, then start over if I noticed a mistake. It worked, but it felt like fighting tooling instead of building ideas.

The turning point came when I was iterating on control systems and electromagnetics visuals. I had dozens of near-identical frames and no clean way to regenerate them when I changed a style or formula. I wanted one source of truth, one command, and outputs that looked publication-ready without manual babysitting.

That frustration became this project: `tikzgif`, a pipeline that takes a parameterized `.tex` file and renders animation formats like GIF, MP4, WebP, and APNG with sane defaults, parallel frame compilation, and reproducible outputs.

![Bouncing Ball](../outputs/02_bouncing_ball.gif)

The promise I wanted for myself was simple: if I can draw it in TikZ, I should be able to animate it without inventing a new workflow each time.

## 2. What Was Broken in My Old Process

Before this repo, my animation loop usually looked like this:

1. Hand-edit parameter values in TeX.
2. Run LaTeX repeatedly.
3. Convert PDFs to PNGs with ad hoc commands.
4. Stitch images with ImageMagick flags I had to keep rediscovering.
5. Re-run everything when the bounding box shifted or one frame failed.

The core issue was not “LaTeX is slow.” The issue was **coordination overhead**. Every stage had separate failure modes and separate tooling assumptions.

- If two frames had slightly different extents, the final animation jittered.
- If one frame failed late, I often re-ran too much work.
- If I switched machines, I had to remember toolchain differences again.
- If I changed one line in the template, I still paid near-full compile cost.

I wanted to keep TikZ itself as the authoring interface, but automate everything around it: frame generation, compilation strategy, caching, conversion, and assembly.

## 3. The Design Target: One Command, Many Outputs

The design goal for `tikzgif` was strict: **I should be able to hand someone a single `.tex` file and one CLI command, and they should get a usable animation artifact**.

That sounds obvious, but it forced a lot of early decisions:

- Keep parameterization dead simple (`\PARAM` token by default).
- Make frame compilation parallel by default.
- Normalize frame extents so output is stable.
- Support more than GIF from day one.
- Auto-detect toolchains and degrade gracefully where possible.

I intentionally did not build a new drawing DSL or ask people to abandon TikZ habits. If you already know how to author diagrams in TeX, this should feel like adding one small convention, not adopting a new ecosystem.

![Gear Train](../outputs/12_gear_train.gif)

## 4. How the Pipeline Actually Runs

At a high level, `tikzgif` turns one parameterized source into an ordered list of frame results, then assembles them.

1. Parse template and detect package/tool requirements.
2. Generate frame specs by replacing the parameter token with interpolated values.
3. Compile frames in parallel in isolated directories.
4. Estimate a stable bounding envelope and normalize output extents.
5. Convert resulting PDFs to images through the best available backend.
6. Assemble target format (GIF/MP4/WebP/APNG/SVG/spritesheet/PDF animation).

The pipeline boundary choices mattered more than any individual trick. Keeping stages explicit made it easier to reason about failure handling (`abort`, `skip`, `retry`) and easier to test each part independently.

I also leaned into deterministic structure where possible: frame index ordering, content hashing, and predictable naming all make debugging far less painful than shell-script style glue.

## 5. Outputs Along the Way, Not Just at the End

One important shift in this repo is that I stopped treating animation as a single opaque output step. I now think in intermediate products:

- **Template source**: the human-readable truth.
- **Per-frame TeX**: generated, explicit, inspectable.
- **Per-frame PDF**: compilation artifact with good debugging value.
- **Per-frame image**: rendering artifact before final encoding.
- **Final animation**: format-specific artifact tuned for destination.

That separation made debugging dramatically easier. If something looks wrong, I can ask: was the math wrong in TeX, did compilation fail, did conversion alter color/alpha, or did assembly quantization introduce artifacts?

These are some of the outputs that made me confident the pipeline was doing the right thing across domains:

![Lorenz Attractor](../outputs/04_lorenz_attractor.gif)

![Bode Plot](../outputs/17_bode_plot.gif)

![Fourier Series](../outputs/21_fourier_series.gif)

For me, this was a major design lesson: the easiest systems to trust are the ones where each stage has visible artifacts and crisp boundaries.
