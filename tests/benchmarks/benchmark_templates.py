"""
Benchmark templates -- minimal, medium, and heavy TikZ sources for
performance profiling.

Each template is a complete, compilable .tex document with a \\PARAM
placeholder.  They are designed to exercise different performance
characteristics of the tikzgif pipeline.
"""

# ---------------------------------------------------------------------------
# SIMPLE:  10 frames, minimal TikZ (a single filled circle)
# Target:  < 1 s per frame, < 15 s total sequential
# ---------------------------------------------------------------------------
SIMPLE_TEX = r"""
\documentclass[tikz]{standalone}
\begin{document}
\begin{tikzpicture}
  \useasboundingbox (-3,-3) rectangle (3,3);
  \fill[red] (0,0) circle (\PARAM);
  \node at (0,-2.5) {\small $r = \PARAM$};
\end{tikzpicture}
\end{document}
"""

SIMPLE_CONFIG = {
    "name": "simple",
    "param_name": "\\PARAM",
    "param_start": 0.5,
    "param_end": 2.5,
    "frame_count": 10,
    "description": "Single filled circle with varying radius (10 frames).",
}


# ---------------------------------------------------------------------------
# MEDIUM:  60 frames, pgfplots with moderate data
# Target:  1-3 s per frame, < 60 s total with 4 cores
# ---------------------------------------------------------------------------
MEDIUM_TEX = r"""
\documentclass[tikz]{standalone}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\begin{document}
\begin{tikzpicture}
  \begin{axis}[
    width=10cm, height=7cm,
    domain=-3:3,
    samples=150,
    axis lines=middle,
    xlabel={$x$}, ylabel={$y$},
    ymin=-1.5, ymax=1.5,
    grid=major,
    grid style={gray!20},
    title={Gaussian envelope: $\sigma = \PARAM$},
  ]
    % Gaussian-modulated cosine
    \addplot[blue!70!black, very thick, smooth]
      {exp(-x^2 / (2 * \PARAM * \PARAM)) * cos(deg(5 * x))};
    % Gaussian envelope
    \addplot[red!50, dashed, thick]
      {exp(-x^2 / (2 * \PARAM * \PARAM))};
    \addplot[red!50, dashed, thick]
      {-exp(-x^2 / (2 * \PARAM * \PARAM))};
  \end{axis}
\end{tikzpicture}
\end{document}
"""

MEDIUM_CONFIG = {
    "name": "medium",
    "param_name": "\\PARAM",
    "param_start": 0.3,
    "param_end": 2.0,
    "frame_count": 60,
    "description": "Gaussian-enveloped cosine with pgfplots (60 frames).",
}


# ---------------------------------------------------------------------------
# HEAVY:  200 frames, 3D surface with many samples
# Target:  5-15 s per frame, benefits hugely from parallelism
# ---------------------------------------------------------------------------
HEAVY_TEX = r"""
\documentclass[tikz]{standalone}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\begin{document}
\begin{tikzpicture}
  \begin{axis}[
    width=10cm, height=8cm,
    view={\PARAM}{30},
    domain=-2:2,
    y domain=-2:2,
    samples=30,
    samples y=30,
    colormap/viridis,
    surface/.append style={
      faceted color=black!40,
      opacity=0.85,
    },
    xlabel={$x$}, ylabel={$y$}, zlabel={$z$},
    title={View angle: $\PARAM^\circ$},
    zmin=-1, zmax=1,
  ]
    \addplot3[surf] {sin(deg(sqrt(x^2 + y^2) * 3.14159)) *
                     exp(-(x^2 + y^2) / 4)};
  \end{axis}
\end{tikzpicture}
\end{document}
"""

HEAVY_CONFIG = {
    "name": "heavy",
    "param_name": "\\PARAM",
    "param_start": 0,
    "param_end": 360,
    "frame_count": 200,
    "description": "Rotating 3D surface with 30x30 grid in pgfplots (200 frames).",
}
