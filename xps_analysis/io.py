"""Read tabular XPS data without guessing ambiguous column assignments."""
from dataclasses import dataclass, field
from pathlib import Path
import re

import numpy as np
import pandas as pd


@dataclass
class Spectrum:
    energy: np.ndarray
    intensity: np.ndarray
    original_energy: np.ndarray = field(init=False, repr=False)
    original_intensity: np.ndarray = field(init=False, repr=False)
    was_reordered: bool = field(init=False)

    def __post_init__(self):
        self.energy = np.asarray(self.energy, dtype=float).copy()
        self.intensity = np.asarray(self.intensity, dtype=float).copy()
        if (self.energy.ndim != 1 or self.intensity.shape != self.energy.shape
                or self.energy.size < 3):
            raise ValueError("Spectrum requires at least three paired 1D points")
        if not (np.isfinite(self.energy).all() and np.isfinite(self.intensity).all()):
            raise ValueError("Spectrum contains nonnumeric or nonfinite values")
        self.original_energy = self.energy.copy()
        self.original_intensity = self.intensity.copy()
        order = np.argsort(self.energy)
        self.was_reordered = not np.array_equal(order, np.arange(len(order)))
        self.energy, self.intensity = self.energy[order], self.intensity[order]
        if np.any(np.diff(self.energy) <= 0):
            raise ValueError("Binding energies must be unique")
        for array in [self.energy, self.intensity, self.original_energy, self.original_intensity]:
            array.setflags(write=False)


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
    # pandas disambiguates repeated headers as Intensity, Intensity.1, etc.
    matches = [col for col in frame.columns
               if _normalize(re.sub(r"\.\d+$", "", str(col))) in aliases[kind]]
    if len(matches) != 1:
        raise ValueError(f"Cannot uniquely identify {kind}; specify its column manually. Available: {list(frame.columns)}")
    return matches[0]


def read_table(path, *, separator=None, header=0, sheet_name=0):
    """Read a single table; UTF-8 BOM is removed before comment/delimiter parsing."""
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        frame = pd.read_excel(path, sheet_name=sheet_name, header=header, engine="openpyxl")
    elif path.suffix.lower() in {".csv", ".txt"}:
        frame = pd.read_csv(path, sep=separator, engine="python", header=header,
                            comment="#", encoding="utf-8-sig")
    else:
        raise ValueError("Supported file formats: CSV, TXT, XLSX")
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("Select one Excel sheet")
    return frame


def spectrum_from_table(frame, energy_column=None, intensity_column=None):
    energy = _column(frame, energy_column, "energy")
    intensity = _column(frame, intensity_column, "intensity")
    if energy == intensity:
        raise ValueError("Energy and intensity must use distinct columns")
    label = str(energy).lower()
    if re.search(r"\b(?:kev|mev|joules?|j|kinetic)\b", label):
        raise ValueError("Binding energy must be in eV, not keV/MeV/J or kinetic energy")
    return Spectrum(pd.to_numeric(frame[energy], errors="raise").to_numpy(),
                    pd.to_numeric(frame[intensity], errors="raise").to_numpy())


def load_spectrum(path, energy_column=None, intensity_column=None, *,
                  separator=None, header=0, sheet_name=0):
    """Columns are exact names or zero-based indices; all energies must be in eV."""
    return spectrum_from_table(read_table(path, separator=separator, header=header,
                                          sheet_name=sheet_name), energy_column, intensity_column)
