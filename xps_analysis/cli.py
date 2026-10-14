import argparse
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from . import load_spectrum, shirley_background, PeakSpec, fit_peaks, plot_spectrum, export_png, export_excel


def main(argv=None):
    parser = argparse.ArgumentParser(description="XPS single-peak analysis")
    parser.add_argument("input", type=Path)
    parser.add_argument("--energy-column", help="Exact column name")
    parser.add_argument("--intensity-column", help="Exact column name")
    parser.add_argument("--energy-index", type=int, help="Zero-based column index")
    parser.add_argument("--intensity-index", type=int)
    parser.add_argument("--headerless", action="store_true")
    parser.add_argument("--separator", help=r"Text separator; use '\t' for tabs or '\s+' for whitespace")
    parser.add_argument("--model", choices=["gaussian", "lorentzian", "voigt"], default="gaussian")
    parser.add_argument("--background", choices=["shirley", "none"], default="shirley")
    parser.add_argument("--output", type=Path, default=Path("analysis_output"))
    args = parser.parse_args(argv)
    if args.energy_column is not None and args.energy_index is not None:
        parser.error("Choose energy column name or index")
    if args.intensity_column is not None and args.intensity_index is not None:
        parser.error("Choose intensity column name or index")
    args.output.mkdir(parents=True, exist_ok=True)
    if any((args.output/name).exists() for name in ["raw.png", "fit.png", "fit.xlsx"]):
        parser.error("Output files already exist; choose a new output directory")
    spectrum = load_spectrum(args.input,
        args.energy_column if args.energy_column is not None else args.energy_index,
        args.intensity_column if args.intensity_column is not None else args.intensity_index,
        header=None if args.headerless else 0,
        separator="\t" if args.separator == r"\t" else args.separator)
    bg = shirley_background(spectrum.energy, spectrum.intensity) if args.background == "shirley" else None
    fit = fit_peaks(spectrum, [PeakSpec(args.model)], background=bg)
    for name, result in [("raw.png", None), ("fit.png", fit)]:
        fig = plot_spectrum(spectrum, result)
        export_png(fig, args.output/name)
        plt.close(fig)
    export_excel(fit, args.output/"fit.xlsx")
    print(fit.peaks.to_string(index=False))
    print(f"R²: {fit.r_squared:.8f}")
    print(f"Results saved to {args.output.resolve()}")
