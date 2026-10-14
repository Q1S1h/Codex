"""XPS plotting with conventional descending binding-energy axis."""
from pathlib import Path
import matplotlib.pyplot as plt


def plot_spectrum(spectrum, fit=None):
    if fit is None:
        fig, ax = plt.subplots(figsize=(8, 5))
    else:
        fig, (ax, residual_ax) = plt.subplots(2, 1, figsize=(8, 7), sharex=True,
                                              gridspec_kw={"height_ratios": [3, 1]})
        ax.plot(spectrum.energy, fit.background, label="Shirley / supplied background")
        ax.plot(spectrum.energy, fit.total_fit, label="Total fit")
        for name, values in fit.model_result.eval_components().items():
            ax.plot(spectrum.energy, values+fit.background, "--", label=name.rstrip("_"))
        residual_ax.plot(spectrum.energy, fit.residual)
        residual_ax.axhline(0, color="gray", linewidth=0.8)
        residual_ax.set_ylabel("Residual")
        residual_ax.set_xlabel("Binding Energy (eV)")
    ax.plot(spectrum.energy, spectrum.intensity, ".", markersize=3, label="Raw spectrum")
    ax.set_xlim(spectrum.energy.max(), spectrum.energy.min())
    ax.set_ylabel("Intensity (input units)")
    if fit is None:
        ax.set_xlabel("Binding Energy (eV)")
    ax.legend()
    fig.tight_layout()
    return fig


def export_png(figure, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=600, format="png")
