# tikzgif -- System Architecture and Data Flow

Version 0.1.0 | J.C. Vaught

This document specifies the complete system architecture for `tikzgif`,
a pipeline that converts parameterized TikZ/LaTeX files into animated
GIFs (and optionally MP4/WebP). Every diagram uses box-drawing characters
for deterministic rendering in any monospaced environment.

---

## 1. High-Level Pipeline Diagram

The complete data flow from user input to final output artifact.

```
 USER INPUT (one of three entry points)
 ========================================
 A) .tex file path       B) template name + params     C) Python API call
    + CLI flags              + CLI flags                   tikzgif.render(...)
        |                        |                              |
        v                        v                              v
 +------+------------------------+------------------------------+-------+
 |                     ENTRY POINT ROUTER                               |
 |  Normalizes all three input forms into a unified RenderRequest       |
 |  containing: source text, parameter ranges, output config            |
 +----------------------------------+-----------------------------------+
                                    |
                                    | RenderRequest
                                    v
 +------------------------------------------------------------------+
 |                    CONFIGURATION RESOLVER                         |
 |                                                                   |
 |  Merge order (lowest to highest precedence):                      |
 |    1. Hardcoded defaults (types.CompilationConfig)                |
 |    2. ~/.config/tikzgif/config.toml                               |
 |    3. ./tikzgif.toml                                              |
 |    4. %%--- TIKZGIF META --- block in .tex file                   |
 |    5. CLI flags / Python API kwargs                               |
 |                                                                   |
 |  Output: ResolvedConfig (frozen dataclass)                        |
 +-------------------------------+----------------------------------+
                                 |
                                 | ResolvedConfig + source text
                                 v
 +------------------------------------------------------------------+
 |                    TEMPLATE ENGINE                                 |
 |                                                                   |
 |  1. parse_template() -- split preamble / body / postamble         |
 |  2. Detect param token (\PARAM or {{{ name }}})                   |
 |  3. Detect required packages, --shell-escape needs                |
 |  4. Compute param_values from range/step/n_frames                 |
 |  5. generate_frame_specs() -- produce N FrameSpec objects         |
 |     Each contains: complete .tex source + SHA-256 content_hash    |
 |                                                                   |
 |  Output: list[FrameSpec]  (length N, typically 20-120)            |
 +-------------------------------+----------------------------------+
                                 |
                                 | list[FrameSpec]
                                 v
               +-----------------+-----------------+
               |                                   |
               v                                   v
 +---------------------------+   +----------------------------------+
 |     CACHE LOOKUP          |   |  BBOX PRE-PASS (if two-pass)    |
 |                           |   |                                  |
 |  For each FrameSpec:      |   |  Compile frames 0, N/4, N/2,    |
 |   hash = content_hash     |   |  3N/4 to measure bounding boxes |
 |   if cache_dir/hash.pdf   |   |  Compute union BoundingBox      |
 |     exists -> CACHE HIT   |   |  Re-inject \useasboundingbox    |
 |     mark cached=True      |   |  into ALL FrameSpecs            |
 |   else -> CACHE MISS      |   |  (regenerate content_hash)      |
 |     pass to compiler      |   |                                  |
 |                           |   |  Output: updated list[FrameSpec] |
 +------------+--------------+   +---------------+------------------+
              |                                  |
              | cache_hits: list[FrameResult]     | uncached: list[FrameSpec]
              |                                  |
              +----------------+-----------------+
                               |
                               v
 +------------------------------------------------------------------+
 |               PARALLEL COMPILATION ENGINE                         |
 |                                                                   |
 |  ProcessPoolExecutor(max_workers=M)                               |
 |                                                                   |
 |  For each uncached FrameSpec:                                     |
 |    1. Write .tex to temp dir                                      |
 |    2. Invoke pdflatex/xelatex/lualatex (subprocess)               |
 |    3. Collect PDF or error message                                |
 |    4. Apply ErrorPolicy (ABORT / SKIP / RETRY)                    |
 |    5. Store PDF in cache under content_hash                       |
 |                                                                   |
 |  Progress: callback(frame_index, total, status)                   |
 |  Output: list[FrameResult] (merged with cache_hits, sorted)       |
 +-------------------------------+----------------------------------+
                                 |
                                 | list[FrameResult]  (ordered by index)
                                 v
 +------------------------------------------------------------------+
 |                 FRAME EXTRACTION                                   |
 |                                                                   |
 |  For each successful FrameResult:                                 |
 |    PDF -> PNG at configured DPI                                   |
 |    Backend selection:                                              |
 |      - pdf2image (poppler) -- default, high quality               |
 |      - PyMuPDF (fitz)      -- fast, no system deps                |
 |      - Ghostscript          -- fallback                           |
 |                                                                   |
 |  Output: list[PIL.Image.Image]  (ordered, RGBA)                   |
 +-------------------------------+----------------------------------+
                                 |
                                 | list[PIL.Image.Image]
                                 v
 +------------------------------------------------------------------+
 |                 IMAGE PROCESSOR                                    |
 |                                                                   |
 |  Sequential pipeline on each frame:                               |
 |    1. Uniform canvas -- pad all frames to max(width) x max(height)|
 |    2. Background fill (white or transparent)                      |
 |    3. Optional trim/crop (remove whitespace border)               |
 |    4. Color quantization (256 colors for GIF)                     |
 |    5. Optional dithering (Floyd-Steinberg)                        |
 |                                                                   |
 |  Output: list[PIL.Image.Image]  (uniform size, quantized)         |
 +-------------------------------+----------------------------------+
                                 |
                                 | list[PIL.Image.Image]
                                 v
 +------------------------------------------------------------------+
 |                 ASSEMBLY ENGINE                                    |
 |                                                                   |
 |  +-- GIF backend (Pillow) ----+                                   |
 |  |   frames + durations       |                                   |
 |  |   loop count, disposal     |                                   |
 |  +----------------------------+                                   |
 |                                                                   |
 |  +-- MP4 backend (ffmpeg) ----+  (optional)                       |
 |  |   frames -> temp PNGs      |                                   |
 |  |   ffmpeg -framerate ...     |                                   |
 |  +----------------------------+                                   |
 |                                                                   |
 |  +-- WebP backend (Pillow) ---+  (optional)                       |
 |  |   frames + durations       |                                   |
 |  |   lossless or lossy        |                                   |
 |  +----------------------------+                                   |
 |                                                                   |
 |  Output: bytes (encoded animation)                                |
 +-------------------------------+----------------------------------+
                                 |
                                 | bytes + metadata
                                 v
 +------------------------------------------------------------------+
 |                 OUTPUT MANAGER                                     |
 |                                                                   |
 |  1. Write final file to destination path                          |
 |  2. Cache final output keyed by (template_hash + param_range)     |
 |  3. Clean up temp directory tree                                  |
 |  4. Print summary: N frames, M cached, K failed, filesize, time  |
 |  5. Return RenderResult to caller (Python API)                    |
 |                                                                   |
 |  Output artifacts:                                                |
 |    - animation.gif / .mp4 / .webp                                 |
 |    - (optional) individual frame PNGs if --keep-frames            |
 |    - (optional) compilation log if --verbose                      |
 +------------------------------------------------------------------+
```


---

## 2. Parallel Compilation Diagram

How N frames are distributed across M worker processes with progress
tracking, error handling, and ordered result collection.

```
  list[FrameSpec]  (N uncached frames, ordered 0..N-1)
  |
  v
 +------------------------------------------------------------------------+
 |                         COMPILATION SCHEDULER                           |
 |                                                                         |
 |  1. Determine M = min(max_workers or cpu_count(), N)                    |
 |  2. Create ProcessPoolExecutor(max_workers=M)                           |
 |  3. Submit all N tasks as futures                                       |
 |  4. Attach frame index to each future for ordered reassembly            |
 +---+--------------------------------------------------------------------+
     |
     | submit(compile_one_frame, frame_spec) for each of N frames
     v
 +------------------------------------------------------------------------+
 |                                                                         |
 |                        PROCESS POOL  (M workers)                        |
 |                                                                         |
 |  Worker 0          Worker 1          Worker 2       ...   Worker M-1    |
 |  +-------------+   +-------------+   +-------------+     +----------+  |
 |  | Frame 0     |   | Frame 1     |   | Frame 2     | ... | Frame    |  |
 |  | Frame M     |   | Frame M+1   |   | Frame M+2   |     | 2M-1    |  |
 |  | Frame 2M    |   | Frame 2M+1  |   | Frame 2M+2  |     | ...     |  |
 |  | ...         |   | ...         |   | ...         |     | N-1     |  |
 |  +------+------+   +------+------+   +------+------+     +----+-----+ |
 |         |                 |                 |                   |       |
 +------------------------------------------------------------------------+
           |                 |                 |                   |
           v                 v                 v                   v
      EACH WORKER EXECUTES compile_one_frame(spec: FrameSpec) -> FrameResult
      =======================================================================
      |
      |  +----------------------------------------------------------+
      |  |  1. CREATE TEMP DIRECTORY                                 |
      |  |     /tmp/tikzgif_XXXXXX/frame_{index}/                   |
      |  |     Write spec.tex_content -> frame_{index}.tex           |
      |  +----------------------------------------------------------+
      |                          |
      |                          v
      |  +----------------------------------------------------------+
      |  |  2. INVOKE LATEX ENGINE (subprocess)                      |
      |  |                                                           |
      |  |     pdflatex -interaction=nonstopmode                     |
      |  |              -halt-on-error                               |
      |  |              -output-directory=<tmpdir>                   |
      |  |              [--shell-escape if needed]                   |
      |  |              frame_{index}.tex                            |
      |  |                                                           |
      |  |     Timeout: config.timeout_per_frame_s (default 30s)     |
      |  +----------------------------------------------------------+
      |                          |
      |                 +--------+--------+
      |                 |                 |
      |                 v                 v
      |           SUCCESS              FAILURE
      |           (exit 0)             (exit != 0 or timeout)
      |              |                    |
      |              v                    v
      |  +-------------------+   +-------------------------------+
      |  | 3a. COLLECT PDF   |   | 3b. APPLY ERROR POLICY        |
      |  |   frame_{i}.pdf   |   |                               |
      |  |   Record time     |   |   ABORT  -> raise immediately |
      |  |   Extract bbox    |   |   RETRY  -> one more attempt  |
      |  +--------+----------+   |   SKIP   -> FrameResult with  |
      |           |              |             success=False      |
      |           |              +------+-------+----------------+
      |           |                     |       |
      |           |                 (retry)  (skip/abort)
      |           |                     |       |
      |           v                     v       v
      |  +----------------------------------------------------------+
      |  |  4. STORE IN CACHE                                       |
      |  |     Copy PDF -> cache_dir / content_hash[:2] /            |
      |  |                             content_hash.pdf              |
      |  |     (only on success)                                     |
      |  +----------------------------------------------------------+
      |                          |
      |                          v
      |                    FrameResult
      |                    (index, success, pdf_path, ...)
      |
      +==============================================================

 +------------------------------------------------------------------------+
 |                    RESULT COLLECTOR & PROGRESS AGGREGATOR                |
 |                                                                         |
 |  futures = { future_i: frame_index_i  for i in 0..N-1 }                |
 |                                                                         |
 |  results: list[FrameResult] = [None] * N   # pre-allocated              |
 |                                                                         |
 |  for future in as_completed(futures):                                   |
 |      idx = futures[future]                                              |
 |      result = future.result()                                           |
 |      results[idx] = result           # maintains original ordering      |
 |      completed += 1                                                     |
 |                                                                         |
 |      +-----------------------------------------------------------+      |
 |      |  PROGRESS CALLBACK                                        |      |
 |      |                                                           |      |
 |      |  callback(                                                |      |
 |      |    frame_index = idx,                                     |      |
 |      |    completed   = completed,                               |      |
 |      |    total       = N,                                       |      |
 |      |    cached      = result.cached,                           |      |
 |      |    success     = result.success,                          |      |
 |      |    time_s      = result.compile_time_s,                   |      |
 |      |  )                                                        |      |
 |      |                                                           |      |
 |      |  CLI renders:  [=====>        ] 37/100  (12 cached)       |      |
 |      +-----------------------------------------------------------+      |
 |                                                                         |
 |      +-----------------------------------------------------------+      |
 |      |  ERROR COLLECTOR                                          |      |
 |      |                                                           |      |
 |      |  if not result.success:                                   |      |
 |      |      errors.append(CompilationError(                      |      |
 |      |          frame_index = idx,                               |      |
 |      |          message     = result.error_message,              |      |
 |      |          tex_snippet = first_20_lines(spec.tex_content),  |      |
 |      |      ))                                                   |      |
 |      +-----------------------------------------------------------+      |
 |                                                                         |
 |  # Merge with cache hits                                                |
 |  for hit in cache_hits:                                                 |
 |      results[hit.index] = hit                                           |
 |                                                                         |
 |  Output: list[FrameResult]  (length N, ordered by index)                |
 |          list[CompilationError]  (length 0..N)                          |
 +------------------------------------------------------------------------+
```


---

## 3. Component Interaction Diagram

How all major components communicate, with data types annotated on
every edge.

```
 +=========================================================================+
 |                        ENTRY POINTS                                      |
 |                                                                          |
 |   +------------------+    +-------------------+    +------------------+  |
 |   |    CLI (click)   |    |  Python API       |    |  Template CLI    |  |
 |   |                  |    |  tikzgif.render() |    |  tikzgif run     |  |
 |   |  tikzgif compile |    |  tikzgif.preview()|    |  <template_name> |  |
 |   |  tikzgif preview |    |  tikzgif.list()   |    |  --param K=2.0   |  |
 |   +--------+---------+    +--------+----------+    +--------+---------+  |
 |            |                       |                        |            |
 |            | (args: Namespace)     | (kwargs: dict)         | (args)     |
 +============+=======================+========================+============+
              |                       |                        |
              +----------+------------+------------------------+
                         |
                         | RenderRequest(source, params, output_cfg)
                         v
              +----------+------------------------------------------+
              |              CONFIG MANAGER                          |
              |                                                     |
              |  Inputs:                                             |
              |    defaults:  CompilationConfig (hardcoded)          |
              |    user_cfg:  ~/.config/tikzgif/config.toml          |
              |    proj_cfg:  ./tikzgif.toml                         |
              |    meta_cfg:  %%--- TIKZGIF META --- from .tex       |
              |    cli_cfg:   CLI flags / API kwargs                 |
              |                                                     |
              |  Output:                                             |
              |    ResolvedConfig (frozen dataclass)                 |
              |      .engine:    LatexEngine                         |
              |      .workers:   int                                 |
              |      .dpi:       int                                 |
              |      .fps:       int                                 |
              |      .n_frames:  int                                 |
              |      .output:    OutputConfig                        |
              |      .cache:     CacheConfig                         |
              |      .error:     ErrorPolicy                         |
              |      .bbox:      str                                 |
              +---+-----------+-------------------------------------+
                  |           |
                  |           | ResolvedConfig
                  |           v
                  |  +--------+------------------------------------------+
                  |  |             TEMPLATE ENGINE                        |
                  |  |                                                    |
                  |  |  Input:  str (raw .tex source) + ResolvedConfig    |
                  |  |                                                    |
                  |  |  Internal steps:                                   |
                  |  |    parse_template() -> ParsedTemplate              |
                  |  |      OR                                            |
                  |  |    template_schema.parse_template() -> Template    |
                  |  |                                                    |
                  |  |    generate_frame_specs() -> list[FrameSpec]       |
                  |  |      OR                                            |
                  |  |    Template.generate_all_frames() -> Iterator      |
                  |  |                                                    |
                  |  |  Output:                                           |
                  |  |    list[FrameSpec]                                 |
                  |  |      .index:        int                            |
                  |  |      .param_value:  float                          |
                  |  |      .tex_content:  str                            |
                  |  |      .content_hash: str (SHA-256)                  |
                  |  +---+--------+--------------------------------------+
                  |       |        |
                  |       |        | list[FrameSpec]
                  |       |        v
                  |       |  +-----+------------------------------------+
                  |       |  |          CACHE MANAGER                    |
                  |       |  |                                          |
                  |       |  |  Input:  list[FrameSpec]                 |
                  |       |  |          CacheConfig                     |
                  |       |  |                                          |
                  |       |  |  Methods:                                |
                  |       |  |    lookup(hash) -> Path | None           |
                  |       |  |    store(hash, pdf_bytes) -> Path        |
                  |       |  |    invalidate(template_hash) -> int      |
                  |       |  |    stats() -> CacheStats                 |
                  |       |  |    prune(max_age, max_size) -> int       |
                  |       |  |                                          |
                  |       |  |  Output:                                 |
                  |       |  |    hits:   list[FrameResult] (cached=T)  |
                  |       |  |    misses: list[FrameSpec]               |
                  |       |  +---+---+-----------+----------------------+
                  |       |       |   |           |
                  |       |       |   |           | misses: list[FrameSpec]
                  |       |       |   |           v
                  |       |       |   |  +--------+----------------------------+
                  |       |       |   |  |    COMPILATION ENGINE                |
                  |       |       |   |  |                                     |
                  |       |       |   |  |  Input:                             |
                  |       |       |   |  |    list[FrameSpec]                  |
                  |       |       |   |  |    CompilationConfig                |
                  |       |       |   |  |                                     |
                  |       |       |   |  |  Internal:                          |
                  |       |       |   |  |    ProcessPoolExecutor(M workers)   |
                  |       |       |   |  |    compile_one_frame(spec) per task |
                  |       |       |   |  |    pdflatex subprocess per frame    |
                  |       |       |   |  |                                     |
                  |       |       |   |  |  Output:                            |
                  |       |       |   |  |    list[FrameResult]                |
                  |       |       |   |  |      .pdf_path: Path               |
                  |       |       |   |  |      .success:  bool               |
                  |       |       |   |  |      .bounding_box: BoundingBox    |
                  |       |       |   |  +---+--------+------------------------+
                  |       |       |   |       |        |
                  |       |       |   |       |        | stores new PDFs
                  |       |       |   |       |        +-------->  CACHE MANAGER
                  |       |       |   |       |
                  |       |       |   |       | list[FrameResult]
                  |       |       |   |       |   (merged: compiled + cached)
                  |       |       |   |       v
                  |       |       |   |  +----+----------------------------+
                  |       |       |   |  |   FRAME EXTRACTOR               |
                  |       |       |   |  |                                 |
                  |       |       |   |  |  Input:                         |
                  |       |       |   |  |    list[FrameResult]            |
                  |       |       |   |  |    dpi: int                     |
                  |       |       |   |  |                                 |
                  |       |       |   |  |  Backends (tried in order):     |
                  |       |       |   |  |    1. pdf2image (poppler)       |
                  |       |       |   |  |    2. PyMuPDF  (fitz)           |
                  |       |       |   |  |    3. ghostscript (gs)          |
                  |       |       |   |  |                                 |
                  |       |       |   |  |  Output:                        |
                  |       |       |   |  |    list[PIL.Image.Image] (RGBA) |
                  |       |       |   |  +---+-----------------------------+
                  |       |       |   |      |
                  |       |       |   |      | list[PIL.Image.Image]
                  |       |       |   |      v
                  |       |       |   |  +---+-----------------------------+
                  |       |       |   |  |   IMAGE PROCESSOR               |
                  |       |       |   |  |                                 |
                  |       |       |   |  |  Input:                         |
                  |       |       |   |  |    list[PIL.Image.Image]        |
                  |       |       |   |  |    ImageConfig                  |
                  |       |       |   |  |                                 |
                  |       |       |   |  |  Steps:                         |
                  |       |       |   |  |    normalize_canvas()           |
                  |       |       |   |  |    apply_background()           |
                  |       |       |   |  |    trim_whitespace()            |
                  |       |       |   |  |    quantize_colors()            |
                  |       |       |   |  |                                 |
                  |       |       |   |  |  Output:                        |
                  |       |       |   |  |    list[PIL.Image.Image] (P)    |
                  |       |       |   |  +---+-----------------------------+
                  |       |       |   |      |
                  |       |       |   |      | list[PIL.Image.Image]
                  |       |       |   |      v
                  |       |       |   |  +---+-----------------------------+
                  |       |       |   |  |   ASSEMBLY ENGINE               |
                  |       |       |   |  |                                 |
                  |       |       |   |  |  Input:                         |
                  |       |       |   |  |    list[PIL.Image.Image]        |
                  |       |       |   |  |    OutputConfig (format, fps,   |
                  |       |       |   |  |      loop, bounce, quality)     |
                  |       |       |   |  |                                 |
                  |       |       |   |  |  Backends:                      |
                  |       |       |   |  |    GIF  -> Pillow save()        |
                  |       |       |   |  |    MP4  -> ffmpeg subprocess    |
                  |       |       |   |  |    WebP -> Pillow save()        |
                  |       |       |   |  |                                 |
                  |       |       |   |  |  Output:                        |
                  |       |       |   |  |    bytes (encoded animation)    |
                  |       |       |   |  +---+-----------------------------+
                  |       |       |   |      |
                  |       |       |   |      | bytes
                  |       |       |   |      v
                  +-------+-------+---+ +---+-----------------------------+
                                        |   OUTPUT MANAGER                |
                                        |                                 |
                                        |  Input:                         |
                                        |    bytes, output_path: Path     |
                                        |    RenderMetadata               |
                                        |                                 |
                                        |  Actions:                       |
                                        |    write file to disk           |
                                        |    cache final artifact         |
                                        |    cleanup temp files           |
                                        |    log summary stats            |
                                        |                                 |
                                        |  Output:                        |
                                        |    RenderResult                 |
                                        |      .output_path: Path         |
                                        |      .file_size: int            |
                                        |      .frame_count: int          |
                                        |      .cache_hits: int           |
                                        |      .failures: int             |
                                        |      .total_time_s: float       |
                                        +---------------------------------+
```


---

## 4. Cache Architecture Diagram

Content-addressable caching at multiple levels: per-frame PDFs,
per-frame PNGs, and final output artifacts.

```
 CACHE KEY COMPUTATION
 =====================

 For per-frame PDF cache:
 +-------------------------------------------------------------------+
 |  key = SHA-256( frame.tex_content )                                |
 |                                                                    |
 |  The tex_content includes:                                         |
 |    - standalone preamble (document class, packages)                |
 |    - \begin{document}                                              |
 |    - body with \PARAM replaced by concrete float value             |
 |    - \useasboundingbox (if injected)                               |
 |    - \end{document}                                                |
 |                                                                    |
 |  Example: "a3f8c2...e901"  (64 hex chars)                         |
 +-------------------------------------------------------------------+

 For template-level invalidation:
 +-------------------------------------------------------------------+
 |  template_hash = SHA-256( preamble + body_with_sentinel )          |
 |                                                                    |
 |  The param token is replaced with <<PARAM_SENTINEL>> so the hash   |
 |  is stable across different parameter values.  When template_hash  |
 |  changes, ALL cached frames for that template are invalidated.     |
 +-------------------------------------------------------------------+

 For final output cache:
 +-------------------------------------------------------------------+
 |  output_key = SHA-256(                                             |
 |      template_hash                                                 |
 |    + sorted(param_values)                                          |
 |    + output_format                                                 |
 |    + dpi                                                           |
 |    + fps                                                           |
 |    + image_processing_config                                       |
 |  )                                                                 |
 +-------------------------------------------------------------------+


 CACHE LOOKUP FLOW
 =================

                       FrameSpec
                          |
                          v
                 +--------+--------+
                 |  Compute hash   |
                 |  (already in    |
                 |  FrameSpec.     |
                 |  content_hash)  |
                 +--------+--------+
                          |
                          v
              +-----------+-----------+
              |  Check output cache   |
              |  Does final .gif with |
              |  output_key exist?    |
              +-----------+-----------+
                          |
                  +-------+-------+
                  |               |
                 YES              NO
                  |               |
                  v               v
          +-------+------+  +----+------------------+
          | Return cached |  | For each FrameSpec:   |
          | final .gif    |  |   Check PDF cache     |
          | (skip entire  |  |   hash[:2]/hash.pdf   |
          | pipeline)     |  +----+--------+---------+
          +--------------+       |        |
                                HIT      MISS
                                 |        |
                                 v        v
                          +------+-+ +----+--------+
                          | Load   | | Compile     |
                          | cached | | .tex -> PDF |
                          | PDF    | | Store in    |
                          +------+-+ | cache       |
                                 |   +----+--------+
                                 |        |
                                 +---+----+
                                     |
                                     v
                            +--------+--------+
                            | Check PNG cache  |
                            | hash_dpi.png     |
                            +--------+--------+
                                     |
                             +-------+-------+
                             |               |
                            HIT             MISS
                             |               |
                             v               v
                       +-----+----+   +------+--------+
                       | Load     |   | Extract PNG   |
                       | cached   |   | from PDF      |
                       | PNG      |   | Store in      |
                       +-----+----+   | PNG cache     |
                             |        +------+--------+
                             |               |
                             +-------+-------+
                                     |
                                     v
                              (continue to Image
                               Processor, Assembly)


 CACHE DIRECTORY STRUCTURE ON DISK
 =================================

 ~/.cache/tikzgif/                        # XDG_CACHE_HOME/tikzgif/
 |
 +-- cache.db                             # SQLite metadata (optional future)
 +-- lockfile                             # flock for concurrent access
 |
 +-- pdf/                                 # Per-frame compiled PDFs
 |   +-- a3/                              # First 2 hex chars of hash (sharding)
 |   |   +-- a3f8c2...e901.pdf            # Content-addressed PDF
 |   |   +-- a3f8c2...e901.meta.json      # {timestamp, engine, compile_time}
 |   |   +-- a31b07...ff02.pdf
 |   |   +-- a31b07...ff02.meta.json
 |   +-- b7/
 |   |   +-- b7e019...3a44.pdf
 |   |   +-- b7e019...3a44.meta.json
 |   +-- ...  (256 possible shard dirs)
 |
 +-- png/                                 # Extracted PNG frames
 |   +-- a3/
 |   |   +-- a3f8c2...e901_300dpi.png     # Key includes DPI
 |   |   +-- a3f8c2...e901_150dpi.png
 |   +-- b7/
 |   |   +-- b7e019...3a44_300dpi.png
 |   +-- ...
 |
 +-- output/                              # Final assembled animations
 |   +-- 7c/
 |   |   +-- 7c4f2a...bb11.gif            # output_key -> final GIF
 |   |   +-- 7c4f2a...bb11.meta.json      # {template, params, timestamp, size}
 |   +-- ...
 |
 +-- tmp/                                 # In-progress compilations
     +-- job_<uuid>/                      # Per-job temp directory
         +-- frame_000/
         |   +-- frame_000.tex
         |   +-- frame_000.pdf
         |   +-- frame_000.log
         |   +-- frame_000.aux
         +-- frame_001/
         +-- ...


 CACHE INVALIDATION TRIGGERS
 ============================

 +-----------------------------------+------------------------------------------+
 | Trigger                           | Action                                   |
 +-----------------------------------+------------------------------------------+
 | Template .tex file modified       | Compare template_structure_hash.         |
 |                                   | If changed: delete ALL pdf/ and png/     |
 |                                   | entries for that template.  output/      |
 |                                   | entries also invalidated.                |
 +-----------------------------------+------------------------------------------+
 | Parameter range changed           | Individual frame hashes change           |
 | (different values, more frames)   | naturally.  Old frames remain valid in   |
 |                                   | cache.  New frames compiled fresh.       |
 |                                   | output/ entry invalidated.               |
 +-----------------------------------+------------------------------------------+
 | DPI changed                       | pdf/ entries remain valid.               |
 |                                   | png/ entries miss (key includes DPI).    |
 |                                   | output/ entry invalidated.               |
 +-----------------------------------+------------------------------------------+
 | LaTeX engine changed              | ALL entries invalidated (different        |
 | (pdflatex -> xelatex)             | engine may produce different output).    |
 +-----------------------------------+------------------------------------------+
 | tikzgif version upgrade           | Meta files contain version.  Major       |
 |                                   | version bump invalidates everything.     |
 +-----------------------------------+------------------------------------------+
 | Manual: tikzgif cache clear       | Delete entire ~/.cache/tikzgif/          |
 +-----------------------------------+------------------------------------------+
 | Manual: tikzgif cache prune       | Delete entries older than --max-age      |
 |                                   | or exceeding --max-size.  LRU eviction.  |
 +-----------------------------------+------------------------------------------+
 | Disk space low                    | Automatic LRU eviction when cache        |
 |                                   | exceeds configured max_cache_size_mb.    |
 +-----------------------------------+------------------------------------------+
```


---

## 5. Configuration Precedence Diagram

How configuration is resolved when the same key is specified at
multiple levels.  Higher layers override lower layers.

```
 PRECEDENCE (highest wins)
 =========================

   LAYER 6 (highest)     Python API kwargs
                          tikzgif.render(dpi=600, engine="xelatex", ...)
                               |
                               | overrides
                               v
   LAYER 5                CLI flags
                          tikzgif compile --dpi 600 --engine xelatex ...
                               |
                               | overrides
                               v
   LAYER 4                Magic comments in .tex file
                          %%--- TIKZGIF META ---
                          %% engine: xelatex
                          %% fps: 24
                          %% frames: 60
                          %%--- END META ---
                               |
                               | overrides
                               v
   LAYER 3                Project-local config
                          ./tikzgif.toml
                          [compilation]
                          engine = "lualatex"
                          dpi = 300
                               |
                               | overrides
                               v
   LAYER 2                User global config
                          ~/.config/tikzgif/config.toml
                          [compilation]
                          max_workers = 8
                          cache_dir = "/fast-ssd/tikzgif-cache"
                               |
                               | overrides
                               v
   LAYER 1 (lowest)       Hardcoded defaults
                          CompilationConfig() in types.py
                          engine = pdflatex
                          dpi = 300
                          max_workers = 0 (auto)
                          timeout = 30s
                          error_policy = retry


 MERGE ALGORITHM
 ===============

 +-------------------------------------------------------------------+
 |                                                                    |
 |  def resolve_config(                                               |
 |      tex_source: str,                                              |
 |      cli_args: dict,                                               |
 |      api_kwargs: dict,                                             |
 |  ) -> ResolvedConfig:                                              |
 |                                                                    |
 |      # Start with hardcoded defaults                               |
 |      cfg = dict(DEFAULT_CONFIG)                                    |
 |                                                                    |
 |      # Layer 2: user global                                        |
 |      user_toml = load_toml("~/.config/tikzgif/config.toml")       |
 |      cfg = deep_merge(cfg, user_toml)                              |
 |                                                                    |
 |      # Layer 3: project local                                      |
 |      proj_toml = load_toml("./tikzgif.toml")                      |
 |      cfg = deep_merge(cfg, proj_toml)                              |
 |                                                                    |
 |      # Layer 4: magic comments from .tex                           |
 |      meta = parse_meta_block(tex_source)                           |
 |      cfg = deep_merge(cfg, meta.to_dict())                         |
 |                                                                    |
 |      # Layer 5: CLI flags (only non-None values)                   |
 |      cli_overrides = {k: v for k, v in cli_args.items()            |
 |                       if v is not None}                             |
 |      cfg = deep_merge(cfg, cli_overrides)                          |
 |                                                                    |
 |      # Layer 6: Python API kwargs (only non-None)                  |
 |      api_overrides = {k: v for k, v in api_kwargs.items()          |
 |                       if v is not None}                             |
 |      cfg = deep_merge(cfg, api_overrides)                          |
 |                                                                    |
 |      return ResolvedConfig(**cfg)                                  |
 |                                                                    |
 +-------------------------------------------------------------------+


 CONFIGURATION KEYS AND THEIR SOURCES
 =====================================

 +--------------------+------+------+------+------+------+------+
 | Key                | Def. | User | Proj | Meta | CLI  | API  |
 |                    | L1   | L2   | L3   | L4   | L5   | L6   |
 +--------------------+------+------+------+------+------+------+
 | engine             |  X   |  X   |  X   |  X   |  X   |  X   |
 | dpi                |  X   |  X   |  X   |  X   |  X   |  X   |
 | max_workers        |  X   |  X   |  X   |      |  X   |  X   |
 | timeout_per_frame  |  X   |  X   |  X   |      |  X   |  X   |
 | error_policy       |  X   |  X   |  X   |      |  X   |  X   |
 | shell_escape       |  X   |  X   |  X   |  X   |  X   |  X   |
 | cache_dir          |  X   |  X   |  X   |      |  X   |  X   |
 | bbox_strategy      |  X   |  X   |  X   |  X   |  X   |  X   |
 | fps                |  X   |  X   |  X   |  X   |  X   |  X   |
 | n_frames           |  X   |  X   |  X   |  X   |  X   |  X   |
 | output_format      |  X   |  X   |  X   |      |  X   |  X   |
 | loop               |  X   |  X   |  X   |  X   |  X   |  X   |
 | bounce             |  X   |  X   |  X   |  X   |  X   |  X   |
 | background_color   |  X   |  X   |  X   |  X   |  X   |  X   |
 | trim               |  X   |  X   |  X   |      |  X   |  X   |
 | keep_frames        |  X   |      |  X   |      |  X   |  X   |
 | verbose            |  X   |  X   |      |      |  X   |      |
 +--------------------+------+------+------+------+------+------+

 TOML FILE FORMAT
 ================

 # ~/.config/tikzgif/config.toml  OR  ./tikzgif.toml

 [compilation]
 engine = "pdflatex"          # pdflatex | xelatex | lualatex
 max_workers = 0              # 0 = auto (cpu_count)
 timeout_per_frame = 30.0     # seconds
 error_policy = "retry"       # abort | skip | retry
 shell_escape = false
 extra_args = []

 [rendering]
 dpi = 300
 fps = 15
 n_frames = 30
 bbox_strategy = "two-pass"   # two-pass | user | postprocess
 background = "white"         # white | transparent | "#RRGGBB"
 trim = true

 [output]
 format = "gif"               # gif | mp4 | webp
 loop = true
 bounce = false
 quality = 85                 # for lossy formats

 [cache]
 enabled = true
 directory = "~/.cache/tikzgif"
 max_size_mb = 2048
 max_age_days = 30
```


---

## 6. Error Handling Flow

What happens at each failure point in the pipeline, how errors
propagate, and what recovery options exist.

```
 ERROR TAXONOMY
 ==============

 +-----------------------------------------------------------------------+
 | Category             | Examples                  | Severity            |
 +-----------------------------------------------------------------------+
 | SYSTEM_DEPENDENCY    | pdflatex not found        | FATAL               |
 |                      | poppler not installed      | DEGRADED (fallback) |
 |                      | ffmpeg not found           | DEGRADED (no MP4)   |
 |                      | ghostscript not found      | DEGRADED (fallback) |
 +-----------------------------------------------------------------------+
 | TEMPLATE_PARSE       | Missing \begin{document}  | FATAL               |
 |                      | Missing param token        | FATAL               |
 |                      | Invalid YAML in META block | FATAL               |
 |                      | Malformed \documentclass   | FATAL               |
 +-----------------------------------------------------------------------+
 | CONFIGURATION        | Invalid engine name        | FATAL               |
 |                      | Invalid parameter range    | FATAL               |
 |                      | n_frames < 1               | FATAL               |
 |                      | Malformed TOML config      | WARNING + defaults  |
 +-----------------------------------------------------------------------+
 | COMPILATION          | LaTeX syntax error         | PER-FRAME           |
 |                      | Undefined control sequence | PER-FRAME           |
 |                      | Missing package            | PER-FRAME or FATAL  |
 |                      | Timeout exceeded           | PER-FRAME           |
 +-----------------------------------------------------------------------+
 | EXTRACTION           | PDF corrupted              | PER-FRAME           |
 |                      | Backend failure            | DEGRADED (fallback) |
 +-----------------------------------------------------------------------+
 | RESOURCE             | Out of disk space          | FATAL               |
 |                      | Out of memory              | FATAL               |
 |                      | Too many open files        | RECOVERABLE         |
 +-----------------------------------------------------------------------+
 | OUTPUT               | Permission denied on path  | FATAL               |
 |                      | ffmpeg encoding failure    | DEGRADED (fallback) |
 +-----------------------------------------------------------------------+


 SYSTEM DEPENDENCY CHECK (runs once at startup)
 ===============================================

                   tikzgif starts
                        |
                        v
              +---------+---------+
              | Check for LaTeX   |
              | engine on PATH    |
              +---------+---------+
                        |
                +-------+-------+
                |               |
              FOUND         NOT FOUND
                |               |
                v               v
           (continue)    +------+---------------------------+
                         | FATAL: SystemDependencyError      |
                         |                                   |
                         | "pdflatex not found. Install      |
                         |  TeX Live: brew install mactex    |
                         |  or: apt install texlive-full"    |
                         |                                   |
                         | Exit code: 2                      |
                         +-----------------------------------+
                |
                v
              +---------+---------+
              | Check for PDF     |
              | extraction backend|
              +---------+---------+
                        |
                +-------+--------+--------+
                |       |        |        |
             pdf2image PyMuPDF   gs    NONE FOUND
                |       |        |        |
                v       v        v        v
            (prefer) (fallback) (last) +--+--------------------+
                                       | FATAL:                |
                                       | "No PDF extraction    |
                                       |  backend. Install     |
                                       |  one of: poppler,     |
                                       |  PyMuPDF, ghostscript"|
                                       | Exit code: 2         |
                                       +-----------------------+
                |
                v
              +---------+---------+
              | Check for ffmpeg  |
              | (only if MP4      |
              |  output requested)|
              +---------+---------+
                        |
                +-------+-------+
                |               |
              FOUND         NOT FOUND
                |               |
                v               v
           (continue)    +------+---------------------------+
                         | WARNING (not fatal):              |
                         | "ffmpeg not found. MP4 output     |
                         |  unavailable. Falling back to     |
                         |  GIF format."                     |
                         +----------------------------------+


 LATEX COMPILATION ERROR (single frame)
 =======================================

     compile_one_frame(spec) called in worker process
                        |
                        v
               +--------+--------+
               | pdflatex returns |
               | exit code != 0  |
               +--------+--------+
                        |
                        v
               +--------+--------+
               | Parse .log file  |
               | Extract:         |
               |  - error line #  |
               |  - error message |
               |  - missing pkgs  |
               +--------+--------+
                        |
                        v
           +------------+------------+
           |            |            |
         ABORT        RETRY        SKIP
           |            |            |
           v            v            v
  +--------+---+ +------+------+ +--+-------------+
  | Raise       | | Re-run      | | Return         |
  | Compilation | | pdflatex    | | FrameResult(   |
  | Error       | | one more    | |   success=F,   |
  | immediately | | time        | |   error_msg=   |
  |             | +------+------+ |   <parsed>)    |
  | All pending |        |        |                |
  | futures are |  +-----+-----+  | Frame skipped  |
  | cancelled   |  |           |  | in final GIF   |
  +-------------+  v           v  +----------------+
              SUCCESS      FAIL AGAIN
                 |              |
                 v              v
           (continue)    +------+------+
                         | Return      |
                         | FrameResult |
                         | success=F   |
                         +-------------+


 ALL FRAMES FAIL
 ================

                   All FrameResults have success=False
                        |
                        v
              +---------+---------+
              | Total failure     |
              | detection         |
              +---------+---------+
                        |
                        v
              +---------+----------------------------------+
              | CompilationError raised with:               |
              |                                             |
              |  "All N frames failed to compile.           |
              |   Most common error:                        |
              |     <aggregated error message>              |
              |                                             |
              |   This usually means the template itself    |
              |   has a LaTeX error (not parameter-         |
              |   dependent). Try compiling frame 0         |
              |   manually:                                 |
              |     pdflatex frame_000.tex                  |
              |                                             |
              |   First failing frame saved to:             |
              |     /tmp/tikzgif_debug/frame_000.tex        |
              |     /tmp/tikzgif_debug/frame_000.log"       |
              |                                             |
              | Exit code: 1                                |
              +---------------------------------------------+


 INVALID PARAMETER RANGE
 ========================

              User provides: --param-min 10 --param-max 5
                        |
                        v
              +---------+---------+
              | Validate params   |
              | in Config Resolver|
              +---------+---------+
                        |
                        v
              +---------+----------------------------------+
              | ConfigurationError:                         |
              |                                             |
              |  "Invalid parameter range: min (10) >       |
              |   max (5). Ensure --param-min < --param-max |
              |   or set step to a negative value for       |
              |   decreasing animations."                   |
              |                                             |
              | Exit code: 1                                |
              +---------------------------------------------+

              User provides: --frames 0
                        |
                        v
              +---------+----------------------------------+
              | ConfigurationError:                         |
              |                                             |
              |  "Frame count must be >= 1, got 0."         |
              |                                             |
              | Exit code: 1                                |
              +---------------------------------------------+


 OUT OF DISK SPACE
 ==================

                   During compilation or cache write
                        |
                        v
              +---------+---------+
              | OSError: [Errno   |
              | 28] No space left |
              | on device         |
              +---------+---------+
                        |
                        v
              +---------+---------+
              | Catch in worker   |
              | or cache manager  |
              +---------+---------+
                        |
                +-------+-------+
                |               |
           In worker       In cache write
                |               |
                v               v
       +--------+------+  +----+------------------+
       | Treat as frame |  | WARNING: "Cache write |
       | failure, apply |  |  failed (disk full).  |
       | ErrorPolicy    |  |  Continuing without   |
       |                |  |  caching this frame."  |
       | If ALL frames  |  |                        |
       | fail -> FATAL  |  | Auto-prune oldest      |
       +--------+------+  | cache entries, retry    |
                |          +----+------------------+
                v               |
           (see "All            v
            frames fail"   (continue, degraded)
            above)


 CONVERSION BACKEND FAILURE
 ===========================

              pdf2image raises exception
                        |
                        v
              +---------+---------+
              | Catch in Frame    |
              | Extractor         |
              +---------+---------+
                        |
                        v
              +---------+---------+
              | Try next backend  |
              | in priority order |
              +---------+---------+
                        |
                +-------+-------+-------+
                |               |       |
             pdf2image       PyMuPDF    gs
             (failed)           |       |
                            +---+---+   |
                            | Try   |   |
                            +---+---+   |
                                |       |
                        +-------+--+    |
                        |          |    |
                      OK        FAIL    |
                        |          |    |
                        v       +--+----+---+
                   (continue)   | Try gs    |
                                +--+--------+
                                   |
                           +-------+--+
                           |          |
                         OK        FAIL
                           |          |
                           v          v
                      (continue) +----+------------------+
                                 | FATAL:                 |
                                 | "All PDF extraction    |
                                 |  backends failed for   |
                                 |  frame N.              |
                                 |                        |
                                 |  pdf2image: <error>    |
                                 |  PyMuPDF:   <error>    |
                                 |  gs:        <error>    |
                                 |                        |
                                 |  The PDF may be        |
                                 |  corrupted. Check:     |
                                 |  <path_to_pdf>"        |
                                 +------------------------+


 ERROR REPORTING SUMMARY
 ========================

 +--------------------------------------------------------------------+
 |                                                                     |
 |  At the end of any run (success or partial failure), tikzgif        |
 |  prints a structured summary:                                       |
 |                                                                     |
 |  +--------------------------------------------------------------+  |
 |  |  tikzgif compilation summary                                  |  |
 |  |                                                               |  |
 |  |  Template:    rotating_square.tex                             |  |
 |  |  Frames:      36 total, 30 compiled, 4 cached, 2 failed      |  |
 |  |  Time:        12.4s (0.41s/frame avg, 8 workers)             |  |
 |  |  Output:      rotating_square.gif (1.2 MB)                   |  |
 |  |                                                               |  |
 |  |  Warnings:                                                    |  |
 |  |    - Frame 17: Overfull \hbox (badness 10000)                 |  |
 |  |    - Frame 22: Missing character in font                      |  |
 |  |                                                               |  |
 |  |  Errors (2 frames skipped):                                   |  |
 |  |    - Frame 31: Undefined control sequence \badmacro           |  |
 |  |    - Frame 35: Dimension too large (param=359.99)             |  |
 |  |                                                               |  |
 |  |  Debug logs: /tmp/tikzgif_debug/job_a1b2c3/                  |  |
 |  +--------------------------------------------------------------+  |
 |                                                                     |
 +--------------------------------------------------------------------+
```


---

## 7. Two-Pass Bounding Box Strategy

The "two-pass" bbox_strategy is a key architectural feature that
ensures all frames have identical dimensions in the final animation,
preventing visual jitter.

```
 PASS 1: SAMPLE BOUNDING BOXES
 ==============================

   list[FrameSpec]  (N frames)
        |
        v
   +----+--------------------------------------------+
   | Select sample frames:                            |
   |   frame 0,  frame N/4,  frame N/2,  frame 3N/4  |
   |   (4 samples to capture extremes of animation)   |
   +----+--------------------------------------------+
        |
        | 4 FrameSpecs (subset)
        v
   +----+--------------------------------------------+
   | Compile 4 samples (parallel, same engine)        |
   | Each produces a tightly cropped standalone PDF   |
   +----+--------------------------------------------+
        |
        | 4 PDFs
        v
   +----+--------------------------------------------+
   | Extract bounding box from each PDF               |
   |                                                  |
   | Method 1: pdfinfo / pdfcrop output               |
   |   MediaBox: [0 0 145.2 98.7]                     |
   |                                                  |
   | Method 2: Ghostscript bbox device                 |
   |   %%BoundingBox: 0 0 145 99                      |
   |   %%HiResBoundingBox: 0.0 0.0 145.2 98.7        |
   |                                                  |
   | -> BoundingBox(0, 0, 145.2, 98.7) for each       |
   +----+--------------------------------------------+
        |
        | 4 BoundingBox objects
        v
   +----+--------------------------------------------+
   | Compute UNION bounding box                       |
   |                                                  |
   |   union = bbox_0                                 |
   |   for bbox in [bbox_1, bbox_2, bbox_3]:          |
   |       union = union.union(bbox)                  |
   |                                                  |
   |   Result: single BoundingBox enclosing all       |
   |   frames at their most extreme extents           |
   +----+--------------------------------------------+
        |
        | enforced_bbox: BoundingBox
        v

 PASS 2: FULL COMPILATION WITH ENFORCED BBOX
 =============================================

   +----+--------------------------------------------+
   | Re-generate ALL N FrameSpecs with enforced_bbox  |
   |                                                  |
   |   generate_frame_specs(                          |
   |       parsed,                                    |
   |       param_values,                              |
   |       enforced_bbox=union_bbox,  <-- injected    |
   |   )                                              |
   |                                                  |
   | Each frame now contains:                         |
   |   \useasboundingbox (x_min, y_min)               |
   |     rectangle (x_max, y_max);                    |
   |                                                  |
   | This forces every frame to the same page size    |
   | even if the drawing content is smaller.          |
   |                                                  |
   | Content hashes are recomputed (bbox is part of   |
   | the .tex content, so the hash changes).          |
   +----+--------------------------------------------+
        |
        | list[FrameSpec]  (N frames, new hashes)
        v
   (proceeds to Cache Lookup -> Compilation -> ...)
```


---

## 8. Module Dependency Graph

How the Python modules within the `tikzgif` package import from
each other.  Arrows point from importer to importee.

```
                          tikzgif/
                             |
          +------------------+------------------+
          |                  |                  |
          v                  v                  v
     __init__.py         types.py        template_schema.py
     (version,           (LatexEngine,    (TemplateMeta,
      public API)         ErrorPolicy,     TemplateParam,
          |               BoundingBox,     Template,
          |               FrameSpec,       parse_template [schema])
          |               FrameResult,         |
          |               CompilationConfig)   |
          |                  ^                  |
          |                  |                  |
          |            +-----+-----+            |
          |            |           |            |
          v            |           v            |
     template.py ------+     config.py  <-------+
     (ParsedTemplate,        (load_toml,
      parse_template,         resolve_config,
      generate_frame_specs,   ResolvedConfig)
      template_structure_hash)     |
          |                        |
          |                        v
          |                  cache.py
          |                  (CacheManager,
          |                   lookup, store,
          |                   invalidate, prune)
          |                        |
          v                        v
     compiler.py  <-----------+----+
     (compile_one_frame,      |
      compile_all_frames,     |
      ProcessPoolExecutor)    |
          |                   |
          v                   |
     extractor.py             |
     (extract_png,            |
      pdf2image / fitz / gs)  |
          |                   |
          v                   |
     processor.py             |
     (normalize_canvas,       |
      quantize, trim)         |
          |                   |
          v                   |
     assembler.py             |
     (assemble_gif,           |
      assemble_mp4,           |
      assemble_webp)          |
          |                   |
          v                   |
     output.py  <-------------+
     (write_output,
      RenderResult,
      cleanup)
          |
          v
     cli/
       __init__.py
       main.py        (click group, entry points)
       commands.py     (compile, preview, cache, list)
       progress.py     (rich progress bar integration)
```


---

## 9. Concurrency and Thread Safety

```
 PROCESS MODEL
 =============

 +-----------------------------------------------------------------------+
 |  MAIN PROCESS (single-threaded event loop)                            |
 |                                                                        |
 |  Responsible for:                                                      |
 |    - Config resolution                                                 |
 |    - Template parsing                                                  |
 |    - Cache lookups (file I/O, but single-threaded)                     |
 |    - Submitting work to process pool                                   |
 |    - Collecting futures (as_completed)                                  |
 |    - Image processing (sequential, Pillow is not thread-safe)          |
 |    - GIF assembly (sequential)                                         |
 |    - Output writing                                                    |
 |                                                                        |
 +------+----------------------------------------------------------------+
        |
        | ProcessPoolExecutor.submit()
        |
        v
 +------+----------------------------------------------------------------+
 |  WORKER PROCESSES (M independent processes, no shared state)           |
 |                                                                        |
 |  Each worker:                                                          |
 |    - Receives a FrameSpec (serialized via pickle)                      |
 |    - Writes .tex to its own temp directory                             |
 |    - Spawns pdflatex as a subprocess                                   |
 |    - Reads the resulting PDF                                           |
 |    - Returns a FrameResult (serialized via pickle)                     |
 |                                                                        |
 |  No shared state between workers.                                      |
 |  No file locks needed (each has unique temp dir).                      |
 |  Cache writes happen in main process after collection.                 |
 |                                                                        |
 +-----------------------------------------------------------------------+

 WHY PROCESSES, NOT THREADS:
   - pdflatex is CPU-bound (no GIL benefit from threads)
   - Subprocess invocation benefits from true parallelism
   - Process isolation: a segfaulting pdflatex does not crash the pool
   - Memory isolation: each LaTeX run can use significant memory

 POTENTIAL BOTTLENECK:
   - Image processing is sequential in main process
   - For very large frame counts (>500), consider chunked parallel
     PNG extraction using ThreadPoolExecutor (I/O-bound, GIL-friendly)
```

---

## 10. File System Layout During a Run

```
 WORKING STATE (during compilation of 36-frame job)
 ==================================================

 /tmp/tikzgif_a1b2c3d4/                    # job temp root (uuid suffix)
 |
 +-- frame_000/
 |   +-- frame_000.tex                      # 2.1 KB (standalone + tikzpicture)
 |   +-- frame_000.pdf                      # 14 KB  (compiled output)
 |   +-- frame_000.aux                      # 0.5 KB (LaTeX auxiliary)
 |   +-- frame_000.log                      # 8 KB   (compilation log)
 |
 +-- frame_001/
 |   +-- frame_001.tex
 |   +-- frame_001.pdf
 |   +-- frame_001.aux
 |   +-- frame_001.log
 |
 +-- ...
 |
 +-- frame_035/
 |   +-- frame_035.tex
 |   +-- frame_035.pdf
 |   +-- frame_035.aux
 |   +-- frame_035.log
 |
 +-- extracted/                              # PNG extraction output
 |   +-- frame_000.png                       # 300 DPI, RGBA
 |   +-- frame_001.png
 |   +-- ...
 |   +-- frame_035.png
 |
 +-- processed/                              # After image normalization
 |   +-- frame_000.png                       # Uniform size, quantized
 |   +-- frame_001.png
 |   +-- ...
 |   +-- frame_035.png
 |
 +-- output/
     +-- animation.gif                       # Final assembled GIF


 FINAL OUTPUT (after cleanup)
 ============================

 ./rotating_square.gif                       # User's requested output
 (temp directory deleted unless --keep-frames)

 If --keep-frames:
 ./rotating_square_frames/
     +-- frame_000.png
     +-- frame_001.png
     +-- ...
     +-- frame_035.png
```

---

*End of architecture document.*
