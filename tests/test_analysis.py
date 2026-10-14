import tempfile
import unittest
from pathlib import Path
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.integrate import cumulative_trapezoid
from lmfit.models import GaussianModel, LorentzianModel, VoigtModel
from PIL import Image

from xps_analysis import (Spectrum, load_spectrum, shirley_background,
                          PeakSpec, fit_peaks, plot_spectrum, export_png, export_excel)


class XPSAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.x = np.linspace(275, 295, 501)
        self.peak = GaussianModel().eval(x=self.x, amplitude=100, center=285, sigma=0.8)

    def test_all_file_formats_and_descending_input(self):
        frame = pd.DataFrame({"Binding Energy (eV)": self.x[::-1], "Intensity (cps)": self.peak[::-1]})
        for suffix in ["csv", "txt", "xlsx"]:
            with self.subTest(suffix=suffix):
                path = self.root/f"data.{suffix}"
                if suffix == "xlsx":
                    frame.to_excel(path, index=False)
                else:
                    frame.to_csv(path, sep="\t" if suffix == "txt" else ",", index=False)
                result = load_spectrum(path)
                np.testing.assert_allclose(result.energy, self.x)
                np.testing.assert_allclose(result.intensity, self.peak, atol=1e-12)

    def test_manual_columns_headerless_whitespace_and_ambiguity(self):
        path = self.root/"manual.csv"
        pd.DataFrame({"E": self.x, "Y": self.peak}).to_csv(path, index=False)
        with self.assertRaisesRegex(ValueError, "manually"):
            load_spectrum(path)
        np.testing.assert_allclose(load_spectrum(path, "E", "Y").intensity, self.peak, atol=1e-12)
        np.testing.assert_allclose(load_spectrum(path, 0, 1).energy, self.x)
        text = self.root/"headerless.txt"
        np.savetxt(text, np.column_stack([self.x, self.peak]))
        np.testing.assert_allclose(load_spectrum(text, 0, 1, header=None, separator=r"\s+").energy, self.x)
        pd.DataFrame({"BE": self.x, "Binding Energy": self.x, "Intensity": self.peak}).to_csv(path, index=False)
        with self.assertRaisesRegex(ValueError, "uniquely"):
            load_spectrum(path)

    def test_chinese_headers(self):
        path = self.root/"chinese.csv"
        pd.DataFrame({"结合能(eV)": self.x, "信号强度": self.peak}).to_csv(path, index=False)
        np.testing.assert_allclose(load_spectrum(path).energy, self.x)

    def test_invalid_data(self):
        for x, y in [([1, 1, 2], [1, 2, 3]), ([1, 2, 3], [1, np.nan, 3]), ([1, 2], [1, 2])]:
            with self.subTest(x=x, y=y), self.assertRaises(ValueError):
                Spectrum(x, y)
        path = self.root/"bad.csv"
        pd.DataFrame({"BE": [1, 2, 3], "Intensity": [1, "bad", 3]}).to_csv(path, index=False)
        with self.assertRaises(ValueError):
            load_spectrum(path)

    def _shirley_data(self):
        # Independent synthetic forward construction using a known integrated peak.
        integral = cumulative_trapezoid(self.peak, self.x, initial=0)
        bg = 5 + 12 * integral/integral[-1]
        return self.peak+bg, bg

    def test_shirley_recovers_known_background_and_input_order(self):
        y, expected = self._shirley_data()
        actual = shirley_background(self.x, y)
        np.testing.assert_allclose(actual, expected, atol=1e-5)
        np.testing.assert_allclose(shirley_background(self.x[::-1], y[::-1]), expected[::-1], atol=1e-5)
        # Nonuniform sampling must be integrated with actual energy coordinates.
        select = np.arange(len(self.x)) % 3 != 0
        select[[0, -1]] = True
        xx, pp = self.x[select], self.peak[select]
        area = cumulative_trapezoid(pp, xx, initial=0)
        bg = 3+7*area/area[-1]
        np.testing.assert_allclose(shirley_background(xx, pp+bg), bg, atol=1e-5)

    def test_shirley_flat_and_failure(self):
        np.testing.assert_allclose(shirley_background(self.x, self.peak+5), 5, atol=1e-10)
        with self.assertRaises(RuntimeError):
            shirley_background(self.x, self._shirley_data()[0], max_iterations=1)
        with self.assertRaises(ValueError):
            shirley_background([0, 1, 2], [1, 2, 3])

    def test_each_peak_model_recovers_noisy_parameters(self):
        for kind, model in [("gaussian", GaussianModel()), ("lorentzian", LorentzianModel()), ("voigt", VoigtModel())]:
            with self.subTest(model=kind):
                kwargs = dict(amplitude=100, center=285, sigma=0.8)
                if kind == "voigt":
                    kwargs["gamma"] = 0.35
                expected = model.eval(x=self.x, **kwargs)
                y = expected + np.random.default_rng(17).normal(0, 0.01, len(self.x))
                result = fit_peaks(Spectrum(self.x, y), [PeakSpec(kind)])
                row = result.peaks.iloc[0]
                self.assertAlmostEqual(row.center_eV, 285, delta=0.005)
                self.assertAlmostEqual(row.area, 100, delta=0.2)
                params = model.make_params(**kwargs)
                self.assertAlmostEqual(row.fwhm_eV, params['fwhm'].value, delta=0.02)
                if kind == "voigt":
                    self.assertAlmostEqual(result.model_result.params['p0_gamma'].value, 0.35, delta=0.02)
                self.assertGreater(result.r_squared, 0.999)
                np.testing.assert_allclose(result.residual, y-result.model_result.best_fit)

    def test_shirley_then_fitting(self):
        y, _ = self._shirley_data()
        spectrum = Spectrum(self.x, y)
        result = fit_peaks(spectrum, background=shirley_background(self.x, y))
        self.assertAlmostEqual(result.peaks.iloc[0].area, 100, delta=0.01)
        self.assertGreater(result.r_squared, 0.999999)
        np.testing.assert_allclose(result.total_fit+result.residual, y)

    def test_multiple_peaks(self):
        y = self.peak+GaussianModel().eval(x=self.x, amplitude=60, center=288, sigma=0.5)
        fit = fit_peaks(Spectrum(self.x, y), [PeakSpec(center=284.8, sigma=0.7, area=90),
                                            PeakSpec(center=288.2, sigma=0.6, area=55)])
        np.testing.assert_allclose(fit.peaks.center_eV, [285, 288], atol=1e-5)
        np.testing.assert_allclose(fit.peaks.area, [100, 60], atol=1e-4)

    def test_fit_invalid_inputs(self):
        spectrum = Spectrum(self.x, self.peak)
        for specs, bg in [([], None), ([PeakSpec('unknown')], None),
                          ([PeakSpec(sigma=-1)], None), ([PeakSpec()], [1, 2]),
                          ([PeakSpec(), PeakSpec()], None)]:
            with self.subTest(specs=specs), self.assertRaises(ValueError):
                fit_peaks(spectrum, specs, background=bg)

    def test_exports_and_axis(self):
        spectrum = Spectrum(self.x, self.peak)
        fit = fit_peaks(spectrum)
        excel = self.root/"fit.xlsx"
        export_excel(fit, excel)
        sheets = pd.read_excel(excel, sheet_name=None)
        self.assertEqual(set(sheets), {"Peaks", "Summary", "Spectrum"})
        np.testing.assert_allclose(sheets['Spectrum'].residual, fit.residual, atol=1e-12)
        self.assertAlmostEqual(sheets['Peaks'].area.iloc[0], 100, delta=1e-5)
        self.assertGreater(sheets['Summary'].r_squared.iloc[0], 0.999999)
        for result in [None, fit]:
            fig = plot_spectrum(spectrum, result)
            self.addCleanup(plt.close, fig)
            self.assertTrue(all(ax.get_xlim()[0] > ax.get_xlim()[1] for ax in fig.axes))
        png = self.root/"fit.png"
        export_png(fig, png)
        with Image.open(png) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertAlmostEqual(image.info['dpi'][0], 600, delta=0.1)
            self.assertEqual(image.size, (4800, 4200))

    def test_cli_end_to_end_and_overwrite_protection(self):
        path = self.root/"spectrum.csv"
        pd.DataFrame({"BE": self.x, "Intensity": self._shirley_data()[0]}).to_csv(path, index=False)
        output = self.root/"results"
        command = [sys.executable, '-m', 'xps_analysis', str(path), '--output', str(output)]
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('R²:', run.stdout)
        self.assertEqual({p.name for p in output.iterdir()}, {'raw.png', 'fit.png', 'fit.xlsx'})
        original = (output/'fit.xlsx').read_bytes()
        rerun = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(rerun.returncode, 0)
        self.assertIn('already exist', rerun.stderr)
        self.assertEqual((output/'fit.xlsx').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
