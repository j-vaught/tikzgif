# Examples

31 animated TikZ examples spanning geometry, mathematics, physics, engineering, and computer science. Each is a single `.tex` file rendered with one command.

---

## Geometry

Visual patterns built from transforms, recursion, and iteration.

**Rotating Square** — the simplest possible tikzgif animation. A square rotates 360 degrees.

<p align="center">
  <img src="outputs/geometry/01_rotating_square.gif" alt="Rotating square" width="400"/>
</p>

**Mandelbrot Zoom** — zooms into the Mandelbrot set boundary, recomputing the escape-time fractal at each frame.

<p align="center">
  <img src="outputs/geometry/02_mandelbrot_zoom.gif" alt="Mandelbrot zoom" width="400"/>
</p>

**Fractal Tree** — a recursive branching tree that grows as the branching depth increases.

**Wave Interference** — two circular wavefronts interfere, producing constructive and destructive patterns as their source separation changes.

<p align="center">
  <img src="outputs/geometry/03_fractal_tree.gif" alt="Fractal tree" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/geometry/04_wave_interference.gif" alt="Wave interference" width="380"/>
</p>

---

## Math

Functions, PDEs, and dynamical systems.

**Sine Wave Phase** — a basic sine wave with a sweeping phase offset. **Function Family** — the power curve y = x^n as the exponent sweeps from 0.3 to 5.

<p align="center">
  <img src="outputs/math/01_sine_wave_phase.gif" alt="Sine wave phase" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/math/02_function_family.gif" alt="Function family" width="380"/>
</p>

**Parametric Curve** — a point traces a Lissajous figure with a velocity vector and component projections.

**Heat Equation** — temperature distribution evolving over time on a 1D rod, solved via PDE discretization.

<p align="center">
  <img src="outputs/math/03_parametric_curve.gif" alt="Parametric curve" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/math/04_heat_equation.gif" alt="Heat equation" width="380"/>
</p>

**Lorenz Attractor** — 3D trajectory of the Lorenz system projected onto a 2D plane, built by Euler integration.

<p align="center">
  <img src="outputs/math/05_lorenz_attractor.gif" alt="Lorenz attractor" width="400"/>
</p>

---

## Signal Processing

Fourier analysis and convolution visualized step by step.

**Fourier Series** — partial sums converging to a square wave as more harmonics are added. Uses LuaLaTeX for fast computation.

<p align="center">
  <img src="outputs/signal_processing/01_fourier_series.gif" alt="Fourier series" width="400"/>
</p>

**Convolution** — four examples of sliding-window convolution with different signal pairs. The flipped kernel slides across the input, and the output builds up in real time.

<p align="center">
  <img src="outputs/signal_processing/02a_convolution_rect_tri.gif" alt="Rect * Tri" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/signal_processing/02b_convolution_rect_rect.gif" alt="Rect * Rect" width="380"/>
</p>

<p align="center">
  <img src="outputs/signal_processing/02c_convolution_tri_tri.gif" alt="Tri * Tri" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/signal_processing/02d_convolution_exp_step.gif" alt="Exp * Step" width="380"/>
</p>

---

## Mechanical

Kinematics, dynamics, and mechanism design.

**Bouncing Ball** — projectile motion with elastic bounces and a fading trail. **Pendulum** — a simple pendulum swinging with an angle trail.

<p align="center">
  <img src="outputs/mechanical/01_bouncing_ball.gif" alt="Bouncing ball" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/mechanical/02_pendulum.gif" alt="Pendulum" width="380"/>
</p>

**Gear Train** — meshing spur gears with correct tooth profiles and speed ratios. **Four-Bar Linkage** — a Grashof crank-rocker mechanism with loop-closure kinematics and coupler path trails.

<p align="center">
  <img src="outputs/mechanical/03_gear_train.gif" alt="Gear train" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/mechanical/04_four_bar_linkage.gif" alt="Four-bar linkage" width="380"/>
</p>

---

## Electromagnetic

Circuits, fields, and wave propagation.

**RC Circuit** — voltage and current transients in an RC circuit as the time constant sweeps. **Electric Field Lines** — field lines and equipotentials from a dipole with adjustable charge separation.

<p align="center">
  <img src="outputs/electromagnetic/01_rc_circuit.gif" alt="RC circuit" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/electromagnetic/02_electric_field_lines.gif" alt="Electric field lines" width="380"/>
</p>

**EM Wave 3D** — E and B fields oscillating perpendicular to the propagation direction. **EM Wave Packet** — a traveling wave packet with Gaussian envelope and energy density visualization.

<p align="center">
  <img src="outputs/electromagnetic/03_em_wave_3d.gif" alt="EM wave 3D" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/electromagnetic/04_em_wave_packet.gif" alt="EM wave packet" width="380"/>
</p>

---

## Controls

Classical control theory across time domain, frequency domain, and stability analysis.

**Step Response** — second-order unit step response sweeping from underdamped to overdamped. **Bode Plot** — magnitude and phase plots of a transfer function as a pole sweeps.

<p align="center">
  <img src="outputs/controls/01_step_response.gif" alt="Step response" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/controls/02_bode_plot.gif" alt="Bode plot" width="380"/>
</p>

**PID Tuning** — step response of a PID-controlled plant as the proportional or derivative gain sweeps.

<p align="center">
  <img src="outputs/controls/03a_pid_kp_sweep.gif" alt="PID Kp sweep" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/controls/03b_pid_kd_sweep.gif" alt="PID Kd sweep" width="380"/>
</p>

**Root Locus** — poles of a three-pole system migrating through the s-plane as loop gain K increases. Uses LuaLaTeX for cubic root solving with branch continuity tracking.

<p align="center">
  <img src="outputs/controls/04_root_locus.gif" alt="Root locus" width="400"/>
</p>

---

## Computers

Digital logic and sorting algorithms.

**Binary Counter** — an 8-bit binary counter incrementing through all 256 states.

<p align="center">
  <img src="outputs/computers/01_binary_counter.gif" alt="Binary counter" width="400"/>
</p>

**Sorting Algorithms** — three classic comparison sorts visualized side by side. Bars are swapped in real time with color-coded comparisons and sorted regions.

<p align="center">
  <img src="outputs/computers/02a_bubble_sort.gif" alt="Bubble sort" width="380"/>
  &nbsp;&nbsp;&nbsp;
  <img src="outputs/computers/02b_selection_sort.gif" alt="Selection sort" width="380"/>
</p>

<p align="center">
  <img src="outputs/computers/02c_insertion_sort.gif" alt="Insertion sort" width="400"/>
</p>
