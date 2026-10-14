"""Composable lmfit peak models; amplitudes represent integrated peak area."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from lmfit.models import GaussianModel, LorentzianModel, VoigtModel

from .io import Spectrum


@dataclass(frozen=True)
class PeakSpec:
    kind: str = "gaussian"
    center: float | None = None
    sigma: float | None = None
    area: float | None = None
    gamma: float | None = None


@dataclass
class FitResult:
    spectrum: Spectrum
    background: np.ndarray
    corrected: np.ndarray
    model_result: object
    peaks: pd.DataFrame
    r_squared: float

    @property
    def residual(self):
        return self.corrected - self.model_result.best_fit

    @property
    def total_fit(self):
        return self.background + self.model_result.best_fit

    @property
    def rmse(self):
        return float(np.sqrt(np.mean(self.residual**2)))


def fit_peaks(spectrum, peaks=None, *, background=None, background_energy=None,
              parameter_settings=None):
    """Fit one or more nonnegative-area peaks to background-corrected data.

    For multiple peaks supply center estimates to prevent identical initialization.
    Voigt gamma is independent of sigma. Widths are always positive.
    Background coordinates must be explicit when the input Spectrum was reordered.
    parameter_settings maps lmfit names to value/min/max/vary/expr settings.
    """
    specs = list(peaks) if peaks is not None else [PeakSpec()]
    if not specs:
        raise ValueError("At least one peak is required")
    x, y = spectrum.energy, spectrum.intensity
    bg = np.zeros_like(y) if background is None else np.asarray(background, dtype=float).copy()
    if bg.shape != y.shape or not np.isfinite(bg).all():
        raise ValueError("Background must match spectrum and be finite")
    if background is not None and background_energy is not None:
        coordinates = np.asarray(background_energy, dtype=float)
        if coordinates.shape != x.shape or not np.isfinite(coordinates).all():
            raise ValueError("Background coordinates must match the spectrum")
        order = np.argsort(coordinates)
        if not np.array_equal(coordinates[order], x):
            raise ValueError("Background coordinates differ from spectrum energy")
        bg = bg[order]
    elif background is not None and spectrum.was_reordered:
        raise ValueError("Specify background_energy for a reordered spectrum to avoid background misalignment")
    corrected = y-bg
    models = {"gaussian": GaussianModel, "lorentzian": LorentzianModel, "voigt": VoigtModel}
    combined, params = None, None
    for i, spec in enumerate(specs):
        kind = spec.kind.lower()
        if kind not in models:
            raise ValueError(f"Unknown peak model: {spec.kind}")
        if len(specs) > 1 and spec.center is None:
            raise ValueError("Provide a center estimate for every peak in a multi-peak fit")
        model = models[kind](prefix=f"p{i}_")
        p = model.guess(corrected, x=x)
        prefix = model.prefix
        for name, value in [("center", spec.center), ("sigma", spec.sigma), ("amplitude", spec.area), ("gamma", spec.gamma)]:
            if value is not None:
                if not np.isfinite(value) or (name != "center" and value <= 0):
                    raise ValueError(f"Invalid {name} estimate")
                if name == "gamma" and kind != "voigt":
                    raise ValueError("gamma applies only to Voigt peaks")
                p[prefix+name].set(value=value)
        p[prefix+"center"].set(min=x.min(), max=x.max())
        p[prefix+"sigma"].set(min=1e-12)
        p[prefix+"amplitude"].set(min=0)
        if kind == "voigt":
            p[prefix+"gamma"].set(expr="", vary=True, min=1e-12,
                                   value=spec.gamma if spec.gamma is not None else p[prefix+"sigma"].value)
        combined = model if combined is None else combined+model
        if params is None:
            params = p
        else:
            params.update(p)
    for name, setting in (parameter_settings or {}).items():
        if name not in params or name.endswith(("fwhm", "height")):
            raise ValueError(f"Unsupported fit parameter: {name}")
        params[name].set(**setting)
    for name, parameter in params.items():
        if parameter.expr:
            continue
        if not np.isfinite(parameter.value) or parameter.min >= parameter.max:
            raise ValueError(f"Invalid parameter or bounds: {name}")
        if name.endswith(("sigma", "gamma")) and parameter.min <= 0:
            raise ValueError(f"Width must have a positive lower bound: {name}")
        if name.endswith("amplitude") and parameter.min < 0:
            raise ValueError("Peak area cannot have a negative lower bound")
    if len(x) <= sum(p.vary for p in params.values()):
        raise ValueError("Insufficient data points for fitted parameters")
    result = combined.fit(corrected, params, x=x, nan_policy="raise")
    if not result.success:
        raise RuntimeError(f"Peak fit failed: {result.message}")
    sst = np.sum((corrected-corrected.mean())**2)
    r2 = float(1-np.sum((corrected-result.best_fit)**2)/sst) if sst > 0 else float("nan")
    rows = []
    for i, spec in enumerate(specs):
        p = result.params
        rows.append({"peak": f"p{i}", "model": spec.kind.lower(),
                     "center_eV": p[f"p{i}_center"].value,
                     "fwhm_eV": p[f"p{i}_fwhm"].value,
                     "area": p[f"p{i}_amplitude"].value,
                     "height": p[f"p{i}_height"].value,
                     "sigma_eV": p[f"p{i}_sigma"].value,
                     "gamma_eV": p[f"p{i}_gamma"].value if spec.kind.lower() == "voigt" else np.nan})
    return FitResult(spectrum, bg, corrected, result, pd.DataFrame(rows), r2)
