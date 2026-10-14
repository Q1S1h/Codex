"""Export peak metrics and pointwise residuals to Excel."""
from pathlib import Path
import pandas as pd


def export_excel(fit, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = pd.DataFrame({"binding_energy_eV": fit.spectrum.energy,
                         "raw_intensity": fit.spectrum.intensity,
                         "background": fit.background, "corrected": fit.corrected,
                         "peak_fit": fit.model_result.best_fit,
                         "total_fit": fit.total_fit, "residual": fit.residual})
    for name, values in fit.model_result.eval_components().items():
        data[name.rstrip("_")] = values
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        fit.peaks.to_excel(writer, sheet_name="Peaks", index=False)
        pd.DataFrame([{"r_squared": fit.r_squared, "success": fit.model_result.success,
                       "chi_square": fit.model_result.chisqr,
                       "reduced_chi_square": fit.model_result.redchi}]).to_excel(writer, sheet_name="Summary", index=False)
        data.to_excel(writer, sheet_name="Spectrum", index=False)
