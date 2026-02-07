"""
Example Gallery Registry for tikzgif.

Each entry describes one complete animation example with its source file,
parameter configuration, CLI invocation, expected output, and metadata.
Run individual examples with:
    tikzgif render tests/examples/tex/<filename>.tex --param PARAM ...

Run all gallery examples:
    python -m pytest tests/examples/test_gallery.py -v
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

EXAMPLES_DIR = Path(__file__).parent / "tex"


@dataclass(frozen=True)
class ExampleSpec:
    """Full specification for one gallery example."""

    name: str
    description: str
    filename: str  # relative to EXAMPLES_DIR
    param_name: str  # LaTeX macro name, e.g. "\\PARAM"
    param_start: float
    param_end: float
    frame_count: int
    cli_command: str  # exact shell command
    expected_width_px: int  # approximate
    expected_height_px: int
    expected_filesize_kb: tuple[int, int]  # (min, max) estimate
    visual_description: str
    difficulty: str  # "beginner" | "intermediate" | "advanced"
    features: list[str] = field(default_factory=list)
    engine: str = "pdflatex"  # "pdflatex" | "xelatex" | "lualatex"
    extra_packages: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def tex_path(self) -> Path:
        return EXAMPLES_DIR / self.filename

    @property
    def param_step(self) -> float:
        if self.frame_count <= 1:
            return 0.0
        return (self.param_end - self.param_start) / (self.frame_count - 1)


# ---------------------------------------------------------------------------
# Gallery entries
# ---------------------------------------------------------------------------

GALLERY: list[ExampleSpec] = [
    # 01 ---------------------------------------------------------------
    ExampleSpec(
        name="Rotating Square",
        description=(
            "A red square rotates 360 degrees around its center, the "
            "simplest possible tikzgif animation and a quick smoke test."
        ),
        filename="01_rotating_square.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=360,
        frame_count=36,
        cli_command=(
            "tikzgif render tests/examples/tex/01_rotating_square.tex "
            "--param PARAM --start 0 --end 360 --frames 36 "
            "--fps 12 -o rotating_square.gif"
        ),
        expected_width_px=300,
        expected_height_px=300,
        expected_filesize_kb=(80, 250),
        visual_description=(
            "A square with dashed diagonals rotates smoothly in the center "
            "of the frame. An angle label at the bottom updates each frame."
        ),
        difficulty="beginner",
        features=[
            "basic parameter substitution",
            "rotation transform",
            "fixed bounding box",
        ],
    ),
    # 02 ---------------------------------------------------------------
    ExampleSpec(
        name="Bouncing Ball",
        description=(
            "A ball follows a parabolic arc across the screen with a ground "
            "shadow that shrinks at the apex."
        ),
        filename="02_bouncing_ball.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=1,
        frame_count=40,
        cli_command=(
            "tikzgif render tests/examples/tex/02_bouncing_ball.tex "
            "--param PARAM --start 0 --end 1 --frames 40 "
            "--fps 20 -o bouncing_ball.gif"
        ),
        expected_width_px=540,
        expected_height_px=360,
        expected_filesize_kb=(120, 400),
        visual_description=(
            "A glossy red ball rises and falls along a dashed parabolic "
            "guide while its shadow on the ground plane compresses and "
            "expands."
        ),
        difficulty="beginner",
        features=[
            "pgfmath expressions in coordinates",
            "shadow effects",
            "smooth trajectory",
        ],
    ),
    # 03 ---------------------------------------------------------------
    ExampleSpec(
        name="Sine Wave Phase Shift",
        description=(
            "A sine wave slides horizontally as the phase parameter sweeps "
            "0 to 360 degrees, with a stationary reference wave."
        ),
        filename="03_sine_wave_phase.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=360,
        frame_count=60,
        cli_command=(
            "tikzgif render tests/examples/tex/03_sine_wave_phase.tex "
            "--param PARAM --start 0 --end 360 --frames 60 "
            "--fps 30 -o sine_wave_phase.gif"
        ),
        expected_width_px=600,
        expected_height_px=300,
        expected_filesize_kb=(200, 600),
        visual_description=(
            "A solid red sine wave slides right while a faint dashed "
            "reference sine wave stays fixed. The title shows the current "
            "phase shift."
        ),
        difficulty="beginner",
        features=[
            "pgfplots integration",
            "trigonometric functions",
            "axis formatting",
        ],
        extra_packages=["pgfplots"],
    ),
    # 04 ---------------------------------------------------------------
    ExampleSpec(
        name="Lorenz Attractor Trace",
        description=(
            "A point traces the Lorenz attractor butterfly in a 3D oblique "
            "projection, with color-coded trail segments."
        ),
        filename="04_lorenz_attractor.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=2000,
        frame_count=200,
        cli_command=(
            "tikzgif render tests/examples/tex/04_lorenz_attractor.tex "
            "--param PARAM --start 0 --end 2000 --frames 200 "
            "--fps 30 -o lorenz_attractor.gif"
        ),
        expected_width_px=720,
        expected_height_px=600,
        expected_filesize_kb=(500, 2000),
        visual_description=(
            "A bright red dot traces the classic Lorenz butterfly. The "
            "trail transitions from cool blue (early) to warm red (recent). "
            "Two lobes of the attractor gradually emerge."
        ),
        difficulty="advanced",
        features=[
            "heavy pgfmath computation",
            "Euler integration in TeX",
            "3D projection",
            "color-graded trail",
        ],
        notes=(
            "Each frame runs ~2000 pgfmath iterations. Expect long compile "
            "times (~10-30s per frame). Parallel compilation essential."
        ),
    ),
    # 05 ---------------------------------------------------------------
    ExampleSpec(
        name="Binary Counter",
        description=(
            "Eight boxes display the binary representation of a number "
            "counting from 0 to 255."
        ),
        filename="05_binary_counter.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=255,
        frame_count=256,
        cli_command=(
            "tikzgif render tests/examples/tex/05_binary_counter.tex "
            "--param PARAM --start 0 --end 255 --frames 256 "
            "--fps 24 -o binary_counter.gif"
        ),
        expected_width_px=540,
        expected_height_px=240,
        expected_filesize_kb=(300, 900),
        visual_description=(
            "Eight boxes in a row flip between white (0) and red (1) to "
            "count upward in binary. Bit-position labels appear below each "
            "box."
        ),
        difficulty="intermediate",
        features=[
            "integer arithmetic",
            "conditional styling",
            "foreach loops",
            "many frames (256)",
        ],
    ),
    # 06 ---------------------------------------------------------------
    ExampleSpec(
        name="Sorting Visualization",
        description=(
            "Vertical bars smoothly interpolate from a shuffled arrangement "
            "to sorted order, with color indicating displacement."
        ),
        filename="06_sorting_visualization.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=1,
        frame_count=30,
        cli_command=(
            "tikzgif render tests/examples/tex/06_sorting_visualization.tex "
            "--param PARAM --start 0 --end 1 --frames 30 "
            "--fps 12 -o sorting.gif"
        ),
        expected_width_px=570,
        expected_height_px=480,
        expected_filesize_kb=(100, 350),
        visual_description=(
            "Eight bars of varying heights slide from shuffled positions "
            "to sorted order. Bars far from their target are red; bars "
            "near their target are blue."
        ),
        difficulty="intermediate",
        features=[
            "position interpolation",
            "conditional coloring",
            "algorithm visualization",
        ],
    ),
    # 07 ---------------------------------------------------------------
    ExampleSpec(
        name="Mandelbrot Zoom",
        description=(
            "A pixel-by-pixel rendering of the Mandelbrot set that "
            "progressively zooms into the Seahorse Valley."
        ),
        filename="07_mandelbrot_zoom.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=1,
        frame_count=60,
        cli_command=(
            "tikzgif render tests/examples/tex/07_mandelbrot_zoom.tex "
            "--param PARAM --start 0 --end 1 --frames 60 "
            "--fps 10 --timeout 120 -o mandelbrot_zoom.gif"
        ),
        expected_width_px=480,
        expected_height_px=360,
        expected_filesize_kb=(400, 1500),
        visual_description=(
            "The Mandelbrot set fills the frame with black interior and "
            "red-to-blue escape-time coloring. The view zooms 1000x into "
            "the Seahorse Valley fractal boundary."
        ),
        difficulty="advanced",
        features=[
            "heavy per-pixel computation",
            "nested foreach loops",
            "escape-time coloring",
            "logarithmic zoom",
        ],
        notes=(
            "40x30 pixel resolution kept deliberately low. Each frame "
            "runs 40*30*30 = 36,000 iterations. Extremely slow in pgfmath "
            "(~60-120s per frame). Use --timeout 120."
        ),
    ),
    # 08 ---------------------------------------------------------------
    ExampleSpec(
        name="Control System Step Response",
        description=(
            "The step response of a second-order system sweeps from "
            "underdamped (oscillatory) to critically damped."
        ),
        filename="08_step_response.tex",
        param_name="\\PARAM",
        param_start=0.05,
        param_end=1.0,
        frame_count=40,
        cli_command=(
            "tikzgif render tests/examples/tex/08_step_response.tex "
            "--param PARAM --start 0.05 --end 1.0 --frames 40 "
            "--fps 10 -o step_response.gif"
        ),
        expected_width_px=660,
        expected_height_px=390,
        expected_filesize_kb=(200, 700),
        visual_description=(
            "A red response curve starts with heavy oscillations (low "
            "damping) and gradually flattens to a monotone rise (critical "
            "damping). An info box tracks zeta, wn, and overshoot."
        ),
        difficulty="intermediate",
        features=[
            "pgfplots function plots",
            "mathematical modeling",
            "engineering visualization",
            "dynamic legend/info box",
        ],
        extra_packages=["pgfplots"],
    ),
    # 09 ---------------------------------------------------------------
    ExampleSpec(
        name="EM Wave Propagation",
        description=(
            "A 3D electromagnetic wave with perpendicular E-field and "
            "B-field oscillations propagating through space."
        ),
        filename="09_em_wave.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=360,
        frame_count=60,
        cli_command=(
            "tikzgif render tests/examples/tex/09_em_wave.tex "
            "--param PARAM --start 0 --end 360 --frames 60 "
            "--fps 24 -o em_wave.gif"
        ),
        expected_width_px=480,
        expected_height_px=540,
        expected_filesize_kb=(300, 1000),
        visual_description=(
            "Red E-field arrows oscillate vertically while blue B-field "
            "arrows oscillate horizontally, both sinusoidal along the "
            "propagation axis. The wave appears to glide forward."
        ),
        difficulty="advanced",
        features=[
            "3D coordinate system",
            "tikz 3d library",
            "field-vector arrows",
            "physics visualization",
        ],
    ),
    # 10 ---------------------------------------------------------------
    ExampleSpec(
        name="RC Circuit Charging",
        description=(
            "An RC circuit diagram shows the capacitor charging "
            "exponentially alongside a real-time voltage plot."
        ),
        filename="10_rc_circuit.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=5,
        frame_count=50,
        cli_command=(
            "tikzgif render tests/examples/tex/10_rc_circuit.tex "
            "--param PARAM --start 0 --end 5 --frames 50 "
            "--fps 15 -o rc_circuit.gif"
        ),
        expected_width_px=600,
        expected_height_px=420,
        expected_filesize_kb=(250, 800),
        visual_description=(
            "Left panel: a schematic RC circuit with current arrows that "
            "fade as charge builds. The capacitor fills with a red bar. "
            "Right panel: a voltage-vs-time curve traced in real time."
        ),
        difficulty="intermediate",
        features=[
            "dual-panel layout",
            "circuit-style drawing",
            "pgfplots subplot",
            "exponential dynamics",
        ],
        extra_packages=["pgfplots"],
    ),
    # 11 ---------------------------------------------------------------
    ExampleSpec(
        name="Pendulum Motion",
        description=(
            "A simple pendulum swings back and forth with a fading trail "
            "of past bob positions."
        ),
        filename="11_pendulum.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=6.28,
        frame_count=60,
        cli_command=(
            "tikzgif render tests/examples/tex/11_pendulum.tex "
            "--param PARAM --start 0 --end 6.28 --frames 60 "
            "--fps 24 -o pendulum.gif"
        ),
        expected_width_px=600,
        expected_height_px=450,
        expected_filesize_kb=(200, 600),
        visual_description=(
            "A pendulum bob swings on a rigid rod from a hatched support. "
            "A ghostly red trail shows the last 12 positions. An angle arc "
            "and label update in real time."
        ),
        difficulty="intermediate",
        features=[
            "trigonometric motion",
            "trail/ghost effect",
            "ball shading",
            "hatching pattern",
        ],
    ),
    # 12 ---------------------------------------------------------------
    ExampleSpec(
        name="Gear Train",
        description=(
            "Two meshing gears with different tooth counts rotate in "
            "opposite directions at the correct gear ratio."
        ),
        filename="12_gear_train.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=360,
        frame_count=72,
        cli_command=(
            "tikzgif render tests/examples/tex/12_gear_train.tex "
            "--param PARAM --start 0 --end 360 --frames 72 "
            "--fps 24 -o gear_train.gif"
        ),
        expected_width_px=660,
        expected_height_px=480,
        expected_filesize_kb=(250, 800),
        visual_description=(
            "A red 16-tooth gear drives a blue 24-tooth gear. The small "
            "gear completes one full revolution while the large gear turns "
            "2/3 of a revolution. Spokes and hubs are visible."
        ),
        difficulty="intermediate",
        features=[
            "parameterized mechanical drawing",
            "gear-ratio math",
            "custom macros with newcommand",
            "inverse rotation",
        ],
    ),
    # 13 ---------------------------------------------------------------
    ExampleSpec(
        name="Signal Convolution",
        description=(
            "A sliding rectangular pulse convolves with a triangle pulse, "
            "with the resulting integral traced in a lower plot."
        ),
        filename="13_signal_convolution.tex",
        param_name="\\PARAM",
        param_start=-2,
        param_end=4,
        frame_count=60,
        cli_command=(
            "tikzgif render tests/examples/tex/13_signal_convolution.tex "
            "--param PARAM --start -2 --end 4 --frames 60 "
            "--fps 15 -o convolution.gif"
        ),
        expected_width_px=600,
        expected_height_px=540,
        expected_filesize_kb=(300, 900),
        visual_description=(
            "Top plot: a red rectangle and a sliding blue triangle overlap, "
            "with the overlap region shaded orange. Bottom plot: the "
            "piecewise convolution integral is traced as a red curve with "
            "a moving dot."
        ),
        difficulty="advanced",
        features=[
            "pgfplots fillbetween library",
            "multi-axis layout",
            "piecewise analytical functions",
            "synchronized dual plots",
        ],
        extra_packages=["pgfplots"],
    ),
    # 14 ---------------------------------------------------------------
    ExampleSpec(
        name="Heat Equation",
        description=(
            "A 1D heat diffusion bar evolves from a sharp initial profile "
            "toward thermal equilibrium, color-coded by temperature."
        ),
        filename="14_heat_equation.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=0.5,
        frame_count=50,
        cli_command=(
            "tikzgif render tests/examples/tex/14_heat_equation.tex "
            "--param PARAM --start 0 --end 0.5 --frames 50 "
            "--fps 15 -o heat_equation.gif"
        ),
        expected_width_px=720,
        expected_height_px=360,
        expected_filesize_kb=(250, 800),
        visual_description=(
            "A horizontal bar transitions from a peaked red center (hot) "
            "with blue edges (cold) toward a uniform lukewarm color. A "
            "temperature profile curve above the bar flattens over time. "
            "A dashed ghost shows the initial condition."
        ),
        difficulty="advanced",
        features=[
            "Fourier series computation in pgfmath",
            "per-pixel color mapping",
            "scientific colorbar legend",
            "PDE visualization",
        ],
    ),
    # 15 ---------------------------------------------------------------
    ExampleSpec(
        name="Fractal Tree Growth",
        description=(
            "A recursive binary tree grows from a single trunk, adding "
            "depth levels progressively with leaves at the tips."
        ),
        filename="15_fractal_tree.tex",
        param_name="\\PARAM",
        param_start=0,
        param_end=1,
        frame_count=60,
        cli_command=(
            "tikzgif render tests/examples/tex/15_fractal_tree.tex "
            "--param PARAM --start 0 --end 1 --frames 60 "
            "--fps 12 -o fractal_tree.gif"
        ),
        expected_width_px=720,
        expected_height_px=660,
        expected_filesize_kb=(200, 800),
        visual_description=(
            "A brown trunk sprouts from the ground and progressively "
            "branches into a full tree canopy. Early branches are thick "
            "and brown; tips are thin and green with small leaf dots. "
            "Each depth level appears as a smooth growth animation."
        ),
        difficulty="advanced",
        features=[
            "recursive TeX macros",
            "conditional drawing by depth",
            "smooth growth interpolation",
            "organic shapes",
        ],
        notes=(
            "Uses \\newcommand recursion which hits TeX's grouping depth. "
            "maxdepth=8 produces 2^8=256 leaf branches. Compilation time "
            "grows exponentially with depth."
        ),
    ),
]


def get_example(name: str) -> ExampleSpec:
    """Look up an example by name (case-insensitive substring match)."""
    name_lower = name.lower()
    for ex in GALLERY:
        if name_lower in ex.name.lower():
            return ex
    raise KeyError(f"No gallery example matching {name!r}")


def list_examples() -> list[str]:
    """Return all example names."""
    return [ex.name for ex in GALLERY]
