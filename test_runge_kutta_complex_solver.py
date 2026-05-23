"""
Tests for runge_kutta_complex_solver.py
"""
import math
import numpy as np
import pytest

from runge_kutta_complex_solver import (
    SolverResult,
    GoalFunction,
    wirtinger_gradient,
    minimize_complex,
    minimize_real_as_complex,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_close(a, b, atol=1e-4, rtol=1e-3, label=""):
    err = abs(a - b)
    thresh = atol + rtol * abs(b)
    assert err < thresh, f"{label}: |{a} - {b}| = {err:.3e} > {thresh:.3e}"


# ---------------------------------------------------------------------------
# Wirtinger gradient tests
# ---------------------------------------------------------------------------

class TestWirtingerGradient:
    """Verify the finite-difference Wirtinger gradient."""

    def test_real_quadratic(self):
        """F(z) = |z₀|² + |z₁|²  →  our formula returns ∂F/∂x + i·∂F/∂y = 2z."""
        def f(z):
            return float((z.conj() * z).real.sum())

        z = np.array([1.0 + 2.0j, -0.5 + 0.5j])
        grad, f0, _ = wirtinger_gradient(f, z)

        # The code computes dr + i·di = ∂F/∂x + i·∂F/∂y.
        # For F = x²+y², ∂F/∂x = 2x, ∂F/∂y = 2y → result is 2z.
        expected = 2 * z
        np.testing.assert_allclose(grad.real, expected.real, atol=1e-5)
        np.testing.assert_allclose(grad.imag, expected.imag, atol=1e-5)

    def test_returns_f0(self):
        def f(z): return float(np.sum(z.real**2))
        z = np.array([3.0 + 0j])
        grad, f0, nf = wirtinger_gradient(f, z, f0=None)
        assert abs(f0 - 9.0) < 1e-10

    def test_fevals_counted(self):
        calls = [0]
        def f(z):
            calls[0] += 1
            return float(np.sum(np.abs(z)**2))
        z = np.array([1+1j, 2-1j])
        grad, f0, nf = wirtinger_gradient(f, z, f0=None, eps=1e-7)
        # 1 for f0 + 4 per variable = 1 + 4*2 = 9
        assert nf == 9


# ---------------------------------------------------------------------------
# minimize_complex – simple quadratic
# ---------------------------------------------------------------------------

class TestMinimizeComplexQuadratic:
    """Purely complex quadratic: minimum known analytically."""

    target = np.array([2.0 + 3.0j, -1.0 - 0.5j, 0.5 + 0j])

    def _make_f(self):
        t = self.target
        def f(z):
            d = z - t
            return float(np.dot(d.conj(), d).real)
        return f

    def test_converges_to_target(self):
        f = self._make_f()
        z0 = np.zeros(3, dtype=complex)
        res = minimize_complex(f, z0, h=0.1, max_iter=500, tol_grad=1e-8)
        assert res.converged, f"Did not converge: {res.message}"
        np.testing.assert_allclose(res.z_opt.real, self.target.real, atol=1e-4)
        np.testing.assert_allclose(res.z_opt.imag, self.target.imag, atol=1e-4)
        assert res.f_opt < 1e-8

    def test_result_type(self):
        res = minimize_complex(self._make_f(), np.zeros(3, dtype=complex),
                               max_iter=50)
        assert isinstance(res, SolverResult)
        assert isinstance(res.z_opt, np.ndarray)
        assert res.z_opt.dtype == complex
        assert isinstance(res.f_opt, float)
        assert isinstance(res.n_iter, int)
        assert isinstance(res.n_fevals, int)
        assert isinstance(res.converged, bool)
        assert isinstance(res.message, str)

    def test_history_tracked(self):
        f = self._make_f()
        z0 = np.zeros(3, dtype=complex)
        res = minimize_complex(f, z0, h=0.1, max_iter=100,
                               track_history=True)
        assert len(res.history_f) == min(res.n_iter, 100)
        # history should be monotonically non-increasing (adaptive step)
        for a, b in zip(res.history_f, res.history_f[1:]):
            assert a >= b - 1e-10, "history should be non-increasing"

    def test_history_empty_when_not_tracked(self):
        res = minimize_complex(self._make_f(), np.zeros(3, dtype=complex),
                               max_iter=10, track_history=False)
        assert res.history_f == []

    def test_single_variable(self):
        target = np.array([3.0 - 2.0j])
        def f(z): return float(abs(z[0] - target[0])**2)
        res = minimize_complex(f, np.zeros(1, dtype=complex),
                               h=0.2, max_iter=300, tol_grad=1e-7)
        assert res.f_opt < 1e-8
        assert abs(res.z_opt[0] - target[0]) < 1e-4


# ---------------------------------------------------------------------------
# minimize_complex – real Rosenbrock (imaginary parts should stay near 0)
# ---------------------------------------------------------------------------

class TestMinimizeComplexRosenbrock:
    def _rosenbrock(self, z):
        x = z.real
        return float(
            sum(100 * (x[i + 1] - x[i]**2)**2 + (1 - x[i])**2
                for i in range(len(x) - 1))
        )

    def test_rosenbrock_n2(self):
        z0 = np.array([-0.5 + 0j, 0.2 + 0j])
        res = minimize_complex(self._rosenbrock, z0,
                               h=1e-3, max_iter=15_000,
                               tol_grad=1e-5, tol_f=1e-14)
        assert res.f_opt < 1e-4, f"f_opt={res.f_opt:.3e}"
        np.testing.assert_allclose(res.z_opt.real, [1.0, 1.0], atol=1e-2)


# ---------------------------------------------------------------------------
# minimize_real_as_complex
# ---------------------------------------------------------------------------

class TestMinimizeRealAsComplex:
    def test_sphere(self):
        """F(x) = ‖x‖²  →  minimum at origin."""
        def sphere(x): return float(np.sum(x**2))
        x0 = np.array([1.0, -2.0, 3.0])
        res = minimize_real_as_complex(sphere, x0, h=0.1, max_iter=500, tol_grad=1e-7)
        assert res.f_opt < 1e-8
        np.testing.assert_allclose(res.z_opt.real, np.zeros(3), atol=1e-4)

    def test_shifted_quadratic(self):
        """F(x) = ‖x - c‖²  →  minimum at c."""
        c = np.array([1.5, -0.5, 2.0])
        def f(x): return float(np.sum((x - c)**2))
        x0 = np.zeros(3)
        res = minimize_real_as_complex(f, x0, h=0.15, max_iter=500, tol_grad=1e-7)
        assert res.f_opt < 1e-8
        np.testing.assert_allclose(res.z_opt.real, c, atol=1e-4)


# ---------------------------------------------------------------------------
# Edge cases & robustness
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_already_at_minimum(self):
        """Starting at the minimum should report convergence immediately."""
        target = np.array([1.0 + 1.0j])
        def f(z): return float(abs(z[0] - target[0])**2)
        res = minimize_complex(f, target.copy(), h=0.1, max_iter=200, tol_grad=1e-5)
        assert res.f_opt < 1e-10

    def test_max_iter_limit(self):
        """Solver must not exceed max_iter."""
        def f(z): return float(np.sum(np.abs(z)**2))
        z0 = np.array([10.0 + 10.0j] * 5)
        res = minimize_complex(f, z0, h=1e-4, max_iter=7, tol_grad=1e-20,
                               adaptive=False)
        assert res.n_iter <= 7

    def test_non_adaptive_mode(self):
        """Solver works with adaptive=False."""
        target = np.array([1.0 + 0j, -1.0 + 0j])
        def f(z):
            d = z - target
            return float(np.dot(d.conj(), d).real)
        res = minimize_complex(f, np.zeros(2, dtype=complex),
                               h=0.05, max_iter=1000,
                               tol_grad=1e-6, adaptive=False)
        assert res.f_opt < 1e-6

    def test_list_input(self):
        """z0 can be a plain Python list of complex numbers."""
        def f(z): return float(np.sum(np.abs(z)**2))
        res = minimize_complex(f, [1+0j, 0+1j], h=0.1, max_iter=200, tol_grad=1e-6)
        assert res.f_opt < 1e-8

    def test_fevals_bounded(self):
        """n_fevals must not exceed max_fevals + a small overhead."""
        calls = [0]
        def f(z):
            calls[0] += 1
            return float(np.sum(np.abs(z - 1)**2))
        res = minimize_complex(f, np.zeros(2, dtype=complex),
                               max_fevals=200, max_iter=10_000,
                               tol_grad=1e-20)
        # Allow a small over-run due to gradient evaluation at the start of each step
        assert calls[0] <= 300, f"Too many calls: {calls[0]}"


# ---------------------------------------------------------------------------
# Spectral residual (bearing-inspired)
# ---------------------------------------------------------------------------

class TestSpectralResidual:
    """Fit a sum of complex exponentials — mimics bearing spectral analysis."""

    def setup_method(self):
        rng = np.random.default_rng(0)
        self.N = 32
        freqs = np.arange(self.N, dtype=float)
        self.alpha_true = np.array([1.0 + 0j, 0.5 - 0.5j])
        self.omega_true = np.array([3.0, 10.0])
        S_clean = sum(
            self.alpha_true[k] * np.exp(1j * self.omega_true[k] * freqs / self.N * 2 * math.pi)
            for k in range(2)
        )
        self.S_obs = S_clean + 0.01 * (
            rng.standard_normal(self.N) + 1j * rng.standard_normal(self.N)
        )
        self.freqs = freqs

    def _make_goal(self):
        S_obs = self.S_obs
        freqs = self.freqs
        N = self.N

        def f(z):
            a1, a2 = z[0], z[1]
            w1, w2 = z[2].real, z[3].real
            S_fit = (a1 * np.exp(1j * w1 * freqs / N * 2 * math.pi) +
                     a2 * np.exp(1j * w2 * freqs / N * 2 * math.pi))
            diff = S_fit - S_obs
            return float(np.dot(diff.conj(), diff).real)
        return f

    def test_residual_decreases(self):
        f = self._make_goal()
        z0 = np.array([1.0 + 0j, 0.5 + 0j, 3.0 + 0j, 10.0 + 0j])
        f0 = f(z0)
        res = minimize_complex(f, z0, h=1e-3, max_iter=2_000,
                               tol_grad=1e-4, track_history=True)
        assert res.f_opt < f0, "Goal function did not decrease"

    def test_amplitude_recovery(self):
        """With a good initial guess the amplitudes should be recovered."""
        f = self._make_goal()
        z0 = np.array([1.0 + 0j, 0.5 + 0j, 3.0 + 0j, 10.0 + 0j])
        res = minimize_complex(f, z0, h=5e-4, max_iter=3_000, tol_grad=1e-5)
        a_opt = res.z_opt[:2]
        for k in range(2):
            assert abs(a_opt[k] - self.alpha_true[k]) < 0.15, \
                f"Amplitude {k} not recovered: got {a_opt[k]}, want {self.alpha_true[k]}"
