"""XPS loading, background correction, fitting and export."""
from .io import Spectrum, load_spectrum
from .background import shirley_background
from .fitting import PeakSpec, FitResult, fit_peaks
from .export import export_excel
from .plotting import plot_spectrum, export_png

__all__ = ["Spectrum", "load_spectrum", "shirley_background", "PeakSpec",
           "FitResult", "fit_peaks", "export_excel", "plot_spectrum", "export_png"]
