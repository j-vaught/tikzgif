# Python File Interaction Diagram

This diagram shows how the real Python files in this repo interact.

- Solid arrows represent direct imports.
- Labels on some arrows show key runtime calls.
- Dashed arrows from tests indicate test-only dependencies.
- macOS metadata files like `._*.py` are excluded.

```mermaid
flowchart LR
  subgraph pkg[tikzgif package]
    INIT["tikzgif/__init__.py"]
    API["tikzgif/api.py"]
    COMP["tikzgif/compiler.py"]
    TEX["tikzgif/tex_gen.py"]
    CACHE["tikzgif/cache.py"]
    ENGINE["tikzgif/engine.py"]
    BBOX["tikzgif/bbox.py"]
    ASM["tikzgif/assembly.py"]
    BACK["tikzgif/backends.py"]
    TYPES["tikzgif/types.py"]
    EXC["tikzgif/exceptions.py"]
    CLIINIT["tikzgif/cli/__init__.py"]
    CLIMAIN["tikzgif/cli/main.py"]
  end

  subgraph tests[tests]
    TCLI["tests/test_cli.py"]
    TAPI["tests/test_api_validation.py"]
    TASM["tests/test_assembly_dispatch.py"]
  end

  INIT --> API
  INIT --> TYPES

  CLIMAIN -->|"render()"| API

  API -->|"compile_single_pass()"| COMP
  API -->|"AnimationAssembler(...).assemble()"| ASM
  API --> BACK
  API --> TYPES

  COMP -->|"parse_template(), generate_frame_specs()"| TEX
  COMP -->|"CompilationCache(...)"| CACHE
  COMP -->|"select_engine(), parse_log(), format_errors()"| ENGINE
  COMP -->|"extract_bbox_from_pdf()"| BBOX
  COMP --> TYPES
  COMP --> EXC

  TEX --> TYPES
  TEX --> EXC

  CACHE --> TYPES

  ENGINE --> TYPES

  BBOX --> TYPES
  BBOX --> EXC

  ASM --> TYPES

  TCLI -.-> CLIMAIN
  TAPI -.-> API
  TASM -.-> ASM
```

## Main Runtime Path

`tikzgif/cli/main.py` -> `tikzgif/api.py` -> `tikzgif/compiler.py` -> (`tikzgif/tex_gen.py`, `tikzgif/cache.py`, `tikzgif/engine.py`, `tikzgif/bbox.py`) -> back to `tikzgif/api.py` -> `tikzgif/backends.py` (PDF to PNG) -> `tikzgif/assembly.py` (GIF/MP4 output).
