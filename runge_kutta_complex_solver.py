"""
Runge-Kutta Complex Solver
==========================
Finds the minimum of a complex-valued goal function of multiple variables
by integrating the Wirtinger gradient flow with adaptive RK4.

Background
----------
For a real-valued cost F(z, z*) depending on complex variables z ∈ ℂⁿ,
the steepest-descent direction in the Wirtinger (CR-calculus) sense is

    dz/dt = -∂F/∂z*       (Wirtinger anti-holomorphic gradient)

We integrate this ODE with a 4th-order Runge-Kutta scheme (RK4) and an
optional adaptive step-size control so the trajectory converges to the
local minimum of F.

Typical use cases in bearing-signal analysis:
  - Fitting complex exponential models to vibration spectra
  - Minimising a spectral residual expressed in the complex domain
  - Any least-squares problem whose residual is naturally complex
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

ComplexArray = np.ndarray   # dtype complex128
GoalFunction = Callable[[ComplexArray], float]


@dataclass
class SolverResult:
    """Container returned by :func:`minimize_complex`."""

    z_opt: ComplexArray
    """Optimal complex variable vector at convergence."""

    f_opt: float
    """Goal-function value at ``z_opt``."""

    n_iter: int
    """Number of RK4 steps taken."""

    n_fevals: int
    """Total number of goal-function evaluations."""

    converged: bool
    """``True`` if the solver met the stopping criterion."""

    history_f: list[float] = field(default_factory=list)
    """Goal-function value recorded at every iteration (if ``track_history=True``)."""

    message: str = ""
    """Human-readable termination reason."""


# ---------------------------------------------------------------------------
# Wirtinger gradient (numerical)
# ---------------------------------------------------------------------------

def wirtinger_gradient(
    f: GoalFunction,
    z: ComplexArray,
    f0: Optional[float] = None,
    eps: float = 1e-7,
) -> tuple[ComplexArray, float, int]:
    """
    Estimate ∂F/∂z* (Wirtinger conjugate gradient) via finite differences.

    For each component zₖ we perturb by ε and iε separately:

        ∂F/∂z*_k ≈ (F(z + εeₖ) - F(z - εeₖ)) / (2ε)
                  + i (F(z + iεeₖ) - F(z - iεeₖ)) / (2ε)

    which equals the CR-calculus gradient with respect to z̄ₖ.

    Parameters
    ----------
    f:
        The goal function F: ℂⁿ → ℝ.
    z:
        Current point in ℂⁿ.
    f0:
        Pre-computed F(z). Computed internally if ``None``.
    eps:
        Finite-difference step size.

    Returns
    -------
    grad : ComplexArray
        Wirtinger gradient ∂F/∂z*.
    f0 : float
        F(z) (possibly freshly computed).
    n_fevals : int
        Number of new F evaluations performed.
    """
    n = z.size
    grad = np.zeros(n, dtype=complex)
    n_fevals = 0

    if f0 is None:
        f0 = f(z)
        n_fevals += 1

    for k in range(n):
        # --- real perturbation ---
        z_p = z.copy(); z_p[k] += eps
        z_m = z.copy(); z_m[k] -= eps
        fp_r = f(z_p); fm_r = f(z_m)
        n_fevals += 2

        # --- imaginary perturbation ---
        z_p = z.copy(); z_p[k] += 1j * eps
        z_m = z.copy(); z_m[k] -= 1j * eps
        fp_i = f(z_p); fm_i = f(z_m)
        n_fevals += 2

        dr = (fp_r - fm_r) / (2 * eps)
        di = (fp_i - fm_i) / (2 * eps)
        # ∂F/∂z* = (∂F/∂x + i ∂F/∂y) / 2  in CR-calculus notation,
        # but numerically the steepest-ascent direction for F w.r.t. z* is:
        grad[k] = dr + 1j * di

    return grad, f0, n_fevals


# ---------------------------------------------------------------------------
# Single RK4 step along gradient flow
# ---------------------------------------------------------------------------

def _rk4_step(
    f: GoalFunction,
    z: ComplexArray,
    f0: float,
    h: float,
    eps: float,
) -> tuple[ComplexArray, float, int]:
    """
    Perform one RK4 step of  dz/dt = -∂F/∂z*  starting at ``z``.

    Returns
    -------
    z_new : ComplexArray
    f_new : float
    n_fevals : int
    """
    total_fevals = 0

    # k1 = -grad at z
    g1, f0, nf = wirtinger_gradient(f, z, f0=f0, eps=eps)
    total_fevals += nf
    k1 = -g1

    # k2 = -grad at z + h/2 * k1
    z2 = z + (h / 2) * k1
    g2, _, nf = wirtinger_gradient(f, z2, eps=eps)
    total_fevals += nf
    k2 = -g2

    # k3 = -grad at z + h/2 * k2
    z3 = z + (h / 2) * k2
    g3, _, nf = wirtinger_gradient(f, z3, eps=eps)
    total_fevals += nf
    k3 = -g3

    # k4 = -grad at z + h * k3
    z4 = z + h * k3
    g4, _, nf = wirtinger_gradient(f, z4, eps=eps)
    total_fevals += nf
    k4 = -g4

    z_new = z + (h / 6) * (k1 + 2 * k2 + 2 * k3 + k4)
    f_new = f(z_new)
    total_fevals += 1

    return z_new, f_new, total_fevals


# ---------------------------------------------------------------------------
# Adaptive step controller (simple PI controller)
# ---------------------------------------------------------------------------

def _adapt_step(
    h: float,
    f_old: float,
    f_new: float,
    h_min: float,
    h_max: float,
    safety: float = 0.9,
    grow_limit: float = 2.0,
    shrink_limit: float = 0.1,
) -> tuple[float, bool]:
    """
    Adjust step size based on whether F decreased.

    A step is accepted if ``f_new < f_old``.  The size is increased on
    acceptance and decreased on rejection.

    Returns
    -------
    h_next : float
    accepted : bool
    """
    if f_new < f_old:
        # accept and grow
        h_next = min(h * safety * grow_limit, h_max)
        return h_next, True
    else:
        # reject and shrink
        h_next = max(h * safety * shrink_limit, h_min)
        return h_next, False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def minimize_complex(
    f: GoalFunction,
    z0: ComplexArray | Sequence[complex],
    *,
    h: float = 1e-2,
    h_min: float = 1e-10,
    h_max: float = 1.0,
    max_iter: int = 5_000,
    max_fevals: int = 500_000,
    tol_grad: float = 1e-6,
    tol_f: float = 1e-12,
    fd_eps: float = 1e-7,
    adaptive: bool = True,
    track_history: bool = False,
    verbose: bool = False,
) -> SolverResult:
    """
    Minimise a real-valued goal function *F* of complex variables via
    Runge-Kutta integration of the Wirtinger gradient flow.

    Parameters
    ----------
    f : GoalFunction
        F : ℂⁿ → ℝ.  Must return a Python ``float`` (or scalar numpy float).
    z0 : array-like of complex
        Initial guess, shape (n,).
    h : float
        Initial RK4 step size (pseudo-time increment).
    h_min / h_max : float
        Bounds for adaptive step control.
    max_iter : int
        Maximum number of RK4 steps.
    max_fevals : int
        Hard limit on total goal-function evaluations.
    tol_grad : float
        Stop when ``‖∂F/∂z*‖₂ < tol_grad``.
    tol_f : float
        Stop when ``|ΔF| / (|F| + 1) < tol_f`` for two successive steps.
    fd_eps : float
        Finite-difference step for Wirtinger gradient estimation.
    adaptive : bool
        Use adaptive step-size control (recommended).
    track_history : bool
        Record ``f`` at every iteration.
    verbose : bool
        Print progress to stdout.

    Returns
    -------
    SolverResult
    """
    z = np.asarray(z0, dtype=complex).ravel().copy()
    n_fevals = 0
    history_f: list[float] = []

    f_cur = float(f(z))
    n_fevals += 1

    n_iter = 0
    consecutive_small_df = 0
    message = "max_iter reached"

    for n_iter in range(1, max_iter + 1):
        if n_fevals >= max_fevals:
            message = "max_fevals reached"
            break

        # --- gradient check ---
        grad, f_cur, nf = wirtinger_gradient(f, z, f0=f_cur, eps=fd_eps)
        n_fevals += nf
        grad_norm = float(np.linalg.norm(grad))

        if track_history:
            history_f.append(f_cur)

        if verbose and (n_iter % max(1, max_iter // 20) == 0 or n_iter == 1):
            print(
                f"  iter {n_iter:5d} | f = {f_cur:.6e} | "
                f"|grad| = {grad_norm:.3e} | h = {h:.3e}"
            )

        if grad_norm < tol_grad:
            message = f"gradient norm {grad_norm:.3e} < tol_grad {tol_grad:.3e}"
            break

        # --- RK4 step ---
        if adaptive:
            # try step; retry with smaller h if not accepted
            max_retries = 50
            accepted = False
            for _ in range(max_retries):
                z_new, f_new, nf = _rk4_step(f, z, f_cur, h, fd_eps)
                n_fevals += nf
                h, accepted = _adapt_step(h, f_cur, f_new, h_min, h_max)
                if accepted:
                    break
                if h <= h_min:
                    accepted = True   # take the step anyway at minimum h
                    break
            if not accepted:
                warnings.warn(
                    "Adaptive step could not decrease F; terminating early.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                message = "adaptive step failed"
                break
        else:
            z_new, f_new, nf = _rk4_step(f, z, f_cur, h, fd_eps)
            n_fevals += nf

        # --- convergence in F ---
        df = abs(f_new - f_cur) / (abs(f_cur) + 1.0)
        if df < tol_f:
            consecutive_small_df += 1
            if consecutive_small_df >= 3:
                message = f"|ΔF|/(|F|+1) < tol_f for 3 consecutive steps"
                z = z_new
                f_cur = f_new
                break
        else:
            consecutive_small_df = 0

        z = z_new
        f_cur = f_new
    else:
        message = "max_iter reached"

    converged = (
        "tol" in message
        or "gradient" in message
    )

    if verbose:
        print(f"\n  Terminated: {message}")
        print(f"  f_opt = {f_cur:.6e}  |  n_iter = {n_iter}  |  n_fevals = {n_fevals}")

    return SolverResult(
        z_opt=z,
        f_opt=f_cur,
        n_iter=n_iter,
        n_fevals=n_fevals,
        converged=converged,
        history_f=history_f,
        message=message,
    )


# ---------------------------------------------------------------------------
# Convenience wrapper: real-variable interface (wraps into complex internally)
# ---------------------------------------------------------------------------

def minimize_real_as_complex(
    f_real: Callable[[np.ndarray], float],
    x0: np.ndarray,
    **kwargs,
) -> SolverResult:
    """
    Thin wrapper that embeds a real variable vector ``x ∈ ℝⁿ`` into ℂⁿ
    and calls :func:`minimize_complex`.

    The goal function ``f_real`` receives a *real* array (the real parts
    of the complex iterate), so existing real-valued cost functions need
    no modification.
    """
    def f_wrapped(z: ComplexArray) -> float:
        return f_real(z.real.copy())

    z0 = np.asarray(x0, dtype=complex)
    return minimize_complex(f_wrapped, z0, **kwargs)


# ---------------------------------------------------------------------------
# Quick demo / smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Runge-Kutta Complex Solver  —  demo")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Example 1: Rosenbrock in the complex domain
    # Treat z = x + iy; goal = Rosenbrock(Re(z₀), Re(z₁))
    # Minimum at z* = (1+0j, 1+0j)
    # ------------------------------------------------------------------
    def rosenbrock_complex(z: ComplexArray) -> float:
        x = z.real
        return float(
            sum(
                100 * (x[i + 1] - x[i] ** 2) ** 2 + (1 - x[i]) ** 2
                for i in range(len(x) - 1)
            )
        )

    z0 = np.array([-0.5 + 0.3j, 0.2 - 0.1j])
    print("\n[1] Rosenbrock (n=2), z0 =", z0)
    res = minimize_complex(
        rosenbrock_complex, z0,
        h=1e-3, max_iter=10_000, tol_grad=1e-5,
        track_history=True, verbose=True,
    )
    print(f"    z_opt  = {res.z_opt}")
    print(f"    f_opt  = {res.f_opt:.4e}  (expected ≈ 0)")
    print(f"    converged: {res.converged}  |  {res.message}")

    # ------------------------------------------------------------------
    # Example 2: purely complex quadratic  F(z) = |z₀ - (2+3j)|² + |z₁ + j|²
    # Minimum at z* = [(2+3j), (0-1j)]
    # ------------------------------------------------------------------
    target = np.array([2 + 3j, -1j])

    def quadratic_complex(z: ComplexArray) -> float:
        diff = z - target
        return float(np.dot(diff.conj(), diff).real)

    z0 = np.array([0.0 + 0j, 0.0 + 0j])
    print("\n[2] Complex quadratic (n=2), z0 =", z0)
    res2 = minimize_complex(
        quadratic_complex, z0,
        h=0.1, max_iter=500, tol_grad=1e-8, adaptive=True,
        track_history=False, verbose=True,
    )
    print(f"    z_opt  = {res2.z_opt}")
    print(f"    target = {target}")
    print(f"    f_opt  = {res2.f_opt:.4e}  (expected ≈ 0)")
    print(f"    converged: {res2.converged}  |  {res2.message}")

    # ------------------------------------------------------------------
    # Example 3: bearing-style spectral residual
    # Fit a sum of K complex exponentials to a noisy spectrum
    # ------------------------------------------------------------------
    print("\n[3] Spectral residual (bearing-style, K=2 modes)")
    rng = np.random.default_rng(42)
    N = 64
    freqs = np.arange(N, dtype=float)

    # True parameters: amplitudes α₁, α₂ (complex) and frequencies ω₁, ω₂ (real)
    alpha_true = np.array([1.5 + 0.5j, 0.8 - 1.2j])
    omega_true = np.array([5.3, 17.9])

    # Synthetic spectrum (sum of complex exponentials + noise)
    S_clean = sum(
        alpha_true[k] * np.exp(1j * omega_true[k] * freqs / N * 2 * np.pi)
        for k in range(2)
    )
    S_obs = S_clean + 0.05 * (rng.standard_normal(N) + 1j * rng.standard_normal(N))

    # Pack parameters: z = [α₁, α₂, ω₁+0j, ω₂+0j]  (4 complex variables)
    def spectral_residual(z: ComplexArray) -> float:
        a1, a2 = z[0], z[1]
        w1, w2 = z[2].real, z[3].real
        S_fit = a1 * np.exp(1j * w1 * freqs / N * 2 * np.pi) + \
                a2 * np.exp(1j * w2 * freqs / N * 2 * np.pi)
        diff = S_fit - S_obs
        return float(np.dot(diff.conj(), diff).real)

    z0_spec = np.array([1.0 + 0j, 1.0 + 0j, 5.0 + 0j, 18.0 + 0j])
    print(f"    Initial residual: {spectral_residual(z0_spec):.4f}")
    res3 = minimize_complex(
        spectral_residual, z0_spec,
        h=1e-3, max_iter=3_000, tol_grad=1e-5,
        adaptive=True, track_history=True, verbose=True,
    )
    print(f"    Final residual  : {res3.f_opt:.4f}")
    print(f"    α_opt  = {res3.z_opt[:2]}")
    print(f"    ω_opt  = {res3.z_opt[2:].real}")
    print(f"    converged: {res3.converged}  |  {res3.message}")
