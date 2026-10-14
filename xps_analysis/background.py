"""Iterative endpoint-anchored Shirley background on ascending binding energy."""
import numpy as np
from scipy.integrate import cumulative_trapezoid


def shirley_background(energy, intensity, *, tolerance=1e-7, max_iterations=1000):
    """Return background in input order; endpoints should bracket the peak region.

    Uses B(E)=y_low+(y_high-y_low)*integral_low^E(y-B)/integral_low^high(y-B).
    No residual clipping is applied. Nonconvergence is reported, never hidden.
    """
    x, y = np.asarray(energy, dtype=float), np.asarray(intensity, dtype=float)
    if x.ndim != 1 or x.shape != y.shape or x.size < 3:
        raise ValueError("Need at least three paired points")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Inputs must be finite")
    if tolerance <= 0 or not np.isfinite(tolerance) or max_iterations < 1:
        raise ValueError("Invalid convergence settings")
    order = np.argsort(x)
    xs, ys = x[order], y[order]
    if np.any(np.diff(xs) <= 0):
        raise ValueError("Binding energies must be unique")
    background = np.interp(xs, [xs[0], xs[-1]], [ys[0], ys[-1]])
    if ys[0] != ys[-1]:
        scale = max(np.max(np.abs(ys)), 1.0)
        for _ in range(max_iterations):
            integral = cumulative_trapezoid(ys-background, xs, initial=0)
            if abs(integral[-1]) <= np.finfo(float).eps * scale * (xs[-1]-xs[0]):
                raise ValueError("Shirley background undefined: negligible integrated peak signal")
            candidate = ys[0] + (ys[-1]-ys[0]) * integral / integral[-1]
            if not np.isfinite(candidate).all():
                raise ValueError("Shirley iteration produced nonfinite values")
            if np.max(np.abs(candidate-background)) <= tolerance * scale:
                background = candidate
                break
            # Damping improves stability for broad peaks.
            background = 0.5 * (background + candidate)
        else:
            raise RuntimeError("Shirley background did not converge; check region endpoints")
    result = np.empty_like(background)
    result[order] = background
    return result
