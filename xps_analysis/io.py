"""Read tabular XPS data without guessing ambiguous column assignments."""
from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
import pandas as pd


@dataclass
class Spectrum:
    energy: np.ndarray
    intensity: np.ndarray

    def __post_init__(self):
        self.energy = np.asarray(self.energy, dtype=float).copy()
        self.intensity = np.asarray(self.intensity, dtype=float).copy()
        if (self.energy.ndim != 1 or self.intensity.shape != self.energy.shape
                or self.energy.size < 3):
            raise ValueError("Spectrum requires at least three paired 1D points")
        if not (np.isfinite(self.energy).all() and np.isfinite(self.intensity).all()):
            raise ValueError("Spectrum contains nonnumeric or nonfinite values")
        order = np.argsort(self.energy)
        self.energy, self.intensity = self.energy[order], self.intensity[order]
        if np.any(np.diff(self.energy) <= 0):
            raise ValueError("Binding energies must be unique")


def _normalize(name):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(name).lower())


def _column(frame, explicit, kind):
    if explicit is not None:
        if isinstance(explicit, int):
            if explicit < 0 or explicit >= len(frame.columns):
                raise ValueError(f"Column index out of range: {explicit}")
            return frame.columns[explicit]
        if explicit not in frame.columns:
            raise ValueError(f"Column {explicit!r} missing; available: {list(frame.columns)}")
        return explicit
    aliases = {
        "energy": {"bindingenergy", "bindingenergyev", "be", "beev", "结合能", "结合能ev"},
        "intensity": {"intensity", "intensitycps", "intensityau", "counts", "countss", "cps", "signal", "信号强度", "强度"},
    }
    matches = [col for col in frame.columns if _normalize(col) in aliases[kind]]
    if len(matches) != 1:
        raise ValueError(f"Cannot uniquely identify {kind}; specify its column manually. Available: {list(frame.columns)}")
    return matches[0]


def load_spectrum(path, energy_column=None, intensity_column=None, *,
                  separator=None, header=0, sheet_name=0):
    """Columns may be exact names or zero-based indices; header=None supports headerless files."""
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        frame = pd.read_excel(path, sheet_name=sheet_name, header=header, engine="openpyxl")
    elif path.suffix.lower() in {".csv", ".txt"}:
        frame = pd.read_csv(path, sep=separator, engine="python", header=header, comment="#")
    else:
        raise ValueError("Supported file formats: CSV, TXT, XLSX")
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("Select one Excel sheet")
    energy = _column(frame, energy_column, "energy")
    intensity = _column(frame, intensity_column, "intensity")
    if energy == intensity:
        raise ValueError("Energy and intensity must use distinct columns")
    return Spectrum(pd.to_numeric(frame[energy], errors="raise").to_numpy(),
                    pd.to_numeric(frame[intensity], errors="raise").to_numpy())
