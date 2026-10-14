"""Independent numerical checks and review regressions.

Regression tests now verify the fixes made during V0.2 development; no tests
are skipped or marked expectedFailure.
"""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.integrate import cumulative_trapezoid, quad
from scipy.optimize import brentq
from scipy.special import voigt_profile, ndtr

from xps_analysis import Spectrum, PeakSpec, load_spectrum, shirley_background, fit_peaks


def gaussian(x, area=100, center=285, sigma=0.8):
    return area / (sigma * np.sqrt(2*np.pi)) * np.exp(-0.5*((x-center)/sigma)**2)


def lorentzian(x, area=100, center=285, sigma=0.8):
    return area * sigma / (np.pi * ((x-center)**2+sigma**2))


def synthetic_shirley():
    x = np.linspace(275, 295, 501)
    peak = gaussian(x)
    area = cumulative_trapezoid(peak, x, initial=0)
    background = 5+12*area/area[-1]
    return x, peak+background, background


class ReviewBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.x = np.linspace(275, 295, 501)

    def test_gaussian_against_independent_definition(self):
        y = gaussian(self.x, area=75, center=284.7, sigma=0.65)
        result = fit_peaks(Spectrum(self.x, y), [PeakSpec('gaussian')])
        np.testing.assert_allclose(result.model_result.best_fit, y, rtol=1e-6, atol=1e-8)
        row = result.peaks.iloc[0]
        self.assertAlmostEqual(row.center_eV, 284.7, delta=1e-6)
        self.assertAlmostEqual(row.area, 75, delta=1e-5)
        self.assertAlmostEqual(row.fwhm_eV, 2*np.sqrt(2*np.log(2))*0.65, delta=1e-5)

    def test_lorentzian_against_independent_definition(self):
        y = lorentzian(self.x, area=75, center=284.7, sigma=0.65)
        result = fit_peaks(Spectrum(self.x, y), [PeakSpec('lorentzian')])
        np.testing.assert_allclose(result.model_result.best_fit, y, rtol=1e-6, atol=1e-8)
        row = result.peaks.iloc[0]
        self.assertAlmostEqual(row.center_eV, 284.7, delta=1e-6)
        self.assertAlmostEqual(row.area, 75, delta=1e-5)
        self.assertAlmostEqual(row.fwhm_eV, 1.3, delta=1e-6)

    def test_voigt_against_scipy_normalized_convolution(self):
        # Reference is scipy.special.voigt_profile, not lmfit's generator.
        for gamma in [0.08, 0.65, 3.0]:
            with self.subTest(gamma=gamma):
                y = 75*voigt_profile(self.x-284.7, 0.65, gamma)
                fit = fit_peaks(Spectrum(self.x, y), [PeakSpec('voigt', center=284.6, sigma=0.7, gamma=gamma, area=70)])
                np.testing.assert_allclose(fit.model_result.best_fit, y, rtol=1e-6, atol=1e-8)
                self.assertAlmostEqual(fit.peaks.area.iloc[0], 75, delta=1e-4)
                self.assertAlmostEqual(fit.model_result.params['p0_sigma'].value, 0.65, delta=1e-5)
                self.assertAlmostEqual(fit.model_result.params['p0_gamma'].value, gamma, delta=1e-5)

    def test_peak_area_against_infinite_domain_quadrature(self):
        for kind, y in [('gaussian', gaussian(self.x)),
                        ('lorentzian', lorentzian(self.x)),
                        ('voigt', 100*voigt_profile(self.x-285, 0.8, 0.35))]:
            with self.subTest(kind=kind):
                fit = fit_peaks(Spectrum(self.x, y), [PeakSpec(kind)])
                def profile(offset):
                    return float(fit.model_result.eval(x=np.array([285+offset]))[0])
                integrated, _ = quad(profile, -np.inf, np.inf, epsabs=1e-7)
                self.assertAlmostEqual(integrated, fit.peaks.area.iloc[0], delta=1e-5)

    def test_voigt_fwhm_approximation_against_exact_half_height(self):
        for ratio in [0.001, 0.01, 0.1, 1, 10, 100]:
            with self.subTest(gamma_sigma_ratio=ratio):
                sigma, gamma = 0.8, 0.8*ratio
                half_height = voigt_profile(0, sigma, gamma)/2
                exact = 2*brentq(lambda t: voigt_profile(t, sigma, gamma)-half_height,
                                0, 10*(sigma+gamma))
                # This is the inspected expression used by lmfit 1.3.4.
                approximate = 1.0692*gamma+np.sqrt(0.8664*gamma**2+5.545083*sigma**2)
                self.assertLess(abs(approximate/exact-1), 3e-4)

    def test_finite_window_area_is_not_model_area(self):
        fit = fit_peaks(Spectrum(self.x, lorentzian(self.x)), [PeakSpec('lorentzian')])
        finite, _ = quad(lambda e: float(fit.model_result.eval(x=np.array([e]))[0]), 275, 295)
        expected = 100*2/np.pi*np.arctan(10/0.8)
        self.assertAlmostEqual(finite, expected, delta=1e-5)
        self.assertLess(finite, fit.peaks.area.iloc[0]-5)

    def test_nonuniform_permuted_noisy_fit_preserves_pairs(self):
        rng = np.random.default_rng(71)
        x = np.sort(rng.uniform(275, 295, 401))
        y = gaussian(x)+rng.normal(0, 0.02, len(x))
        order = rng.permutation(len(x))
        spectrum = Spectrum(x[order], y[order])
        np.testing.assert_array_equal(spectrum.energy, x)
        np.testing.assert_array_equal(spectrum.intensity, y)
        fit = fit_peaks(spectrum)
        self.assertAlmostEqual(fit.peaks.center_eV.iloc[0], 285, delta=0.005)
        self.assertAlmostEqual(fit.peaks.area.iloc[0], 100, delta=0.2)

    def test_negative_noise_is_preserved_not_clipped(self):
        y = gaussian(self.x)+np.random.default_rng(33).normal(0, 0.1, len(self.x))
        self.assertTrue(np.any(y < 0))
        spectrum = Spectrum(self.x, y)
        np.testing.assert_array_equal(spectrum.intensity, y)
        fit = fit_peaks(spectrum)
        np.testing.assert_array_equal(fit.corrected, y)
        self.assertAlmostEqual(fit.peaks.area.iloc[0], 100, delta=0.5)

    def test_missing_values_rejected_in_every_file_format(self):
        for suffix in ['csv', 'txt', 'xlsx']:
            with self.subTest(suffix=suffix):
                frame = pd.DataFrame({'BE': [1, 2, 3, 4], 'Intensity': [10, np.nan, 30, 40]})
                path = self.root/f'missing.{suffix}'
                if suffix == 'xlsx':
                    frame.to_excel(path, index=False)
                else:
                    frame.to_csv(path, sep='\t' if suffix == 'txt' else ',', index=False)
                with self.assertRaises(ValueError):
                    load_spectrum(path)

    def test_nonfinite_invalid_shapes_and_duplicate_energy(self):
        for x, y in [([1, 2, np.inf], [2, 3, 4]), ([1, 2, 3], [2, -np.inf, 4]),
                     ([1, 2, np.nan], [2, 3, 4]), ([[1, 2, 3]], [[2, 3, 4]]),
                     ([1, 2, 3], [2, 3]), ([1, 2, 2], [2, 3, 4])]:
            with self.subTest(x=x, y=y), self.assertRaises(ValueError):
                Spectrum(x, y)
            with self.subTest(shirley_x=x), self.assertRaises(ValueError):
                shirley_background(x, y)

    def test_delimiter_inference(self):
        for sep in [',', ';', '\t']:
            with self.subTest(separator=sep):
                path = self.root/'spectrum.txt'
                frame = pd.DataFrame({'BE': [3, 2, 1], 'Intensity': [30, 20, 10]})
                path.write_text(frame.to_csv(index=False, sep=sep), encoding='utf-8')
                data = load_spectrum(path)
                np.testing.assert_array_equal(data.energy, [1, 2, 3])
                np.testing.assert_array_equal(data.intensity, [10, 20, 30])

    def test_bom_without_comment_and_comment_without_bom(self):
        for prefix in ['\ufeff', '# instrument comment\n']:
            with self.subTest(prefix=prefix):
                path = self.root/'prefix.csv'
                path.write_text(prefix+'BE,Intensity\n3,30\n2,20\n1,10\n', encoding='utf-8')
                spectrum = load_spectrum(path)
                np.testing.assert_array_equal(spectrum.energy, [1, 2, 3])


    def test_excel_sheet_selection_and_headerless(self):
        path = self.root/'sheets.xlsx'
        frame = pd.DataFrame({'BE': [3, 2, 1], 'Intensity': [30, 20, 10]})
        with pd.ExcelWriter(path) as writer:
            pd.DataFrame({'metadata': ['device']}).to_excel(writer, sheet_name='Info', index=False)
            frame.to_excel(writer, sheet_name='Data', index=False)
        np.testing.assert_array_equal(load_spectrum(path, sheet_name='Data').intensity, [10, 20, 30])
        with self.assertRaises(ValueError):
            load_spectrum(path, sheet_name=None)
        path = self.root/'headerless.xlsx'
        frame.to_excel(path, index=False, header=False)
        np.testing.assert_array_equal(load_spectrum(path, 0, 1, header=None).energy, [1, 2, 3])

    def test_bad_file_and_column_choices_fail(self):
        path = self.root/'data.csv'
        pd.DataFrame({'BE': [1, 2, 3], 'Intensity': [2, 3, 4]}).to_csv(path, index=False)
        for energy, intensity in [('missing', 'Intensity'), (-1, 1), (3, 1), (0, 0)]:
            with self.subTest(energy=energy), self.assertRaises(ValueError):
                load_spectrum(path, energy, intensity)
        with self.assertRaises(FileNotFoundError):
            load_spectrum(self.root/'absent.csv')
        with self.assertRaises(ValueError):
            load_spectrum(self.root/'unsupported.json')

    def test_r_squared_and_residual_against_independent_formula(self):
        x, y, bg = synthetic_shirley()
        y = y+np.random.default_rng(23).normal(0, 0.1, len(y))
        fit = fit_peaks(Spectrum(x, y), background=bg)
        corrected = y-bg
        residual = y-(bg+fit.model_result.best_fit)
        expected_r2 = 1-np.dot(residual, residual)/np.dot(corrected-corrected.mean(), corrected-corrected.mean())
        np.testing.assert_allclose(fit.residual, residual, atol=1e-12)
        self.assertAlmostEqual(fit.r_squared, expected_r2, places=12)

    def test_negative_r_squared_is_not_clamped(self):
        # Negative corrected intensity cannot be reproduced by nonnegative-area peaks.
        y = -1+0.1*np.sin(self.x)
        fit = fit_peaks(Spectrum(self.x, y))
        self.assertLess(fit.r_squared, 0)

    def test_constant_zero_signal_r_squared_is_undefined(self):
        for level in [0, 1, -1]:
            with self.subTest(level=level):
                fit = fit_peaks(Spectrum(self.x, np.full_like(self.x, level)))
                self.assertTrue(np.isnan(fit.r_squared))
                # Optimizer success is not a claim that a real peak was detected.
                np.testing.assert_allclose(fit.residual,
                    level-fit.model_result.best_fit, atol=1e-12)

    def test_background_subtracted_once_in_supported_workflow(self):
        x, y, bg = synthetic_shirley()
        raw_fit = fit_peaks(Spectrum(x, y), background=bg)
        pre_corrected_fit = fit_peaks(Spectrum(x, y-bg))
        np.testing.assert_allclose(raw_fit.corrected, y-bg)
        np.testing.assert_allclose(raw_fit.model_result.best_fit, pre_corrected_fit.model_result.best_fit)
        np.testing.assert_allclose(raw_fit.total_fit, raw_fit.model_result.best_fit+bg)

    def test_shirley_random_order_negative_offset_and_reversed_step(self):
        x, y, bg = synthetic_shirley()
        order = np.random.default_rng(83).permutation(len(x))
        np.testing.assert_allclose(shirley_background(x[order], y[order]), bg[order], atol=1e-5)
        np.testing.assert_allclose(shirley_background(x, y-100), bg-100, atol=1e-5)
        # Endpoints of either mathematical ordering are supported.
        peak = gaussian(x)
        down_bg = 22-bg
        np.testing.assert_allclose(shirley_background(x, peak+down_bg), down_bg, atol=1e-5)

    def test_shirley_noise_endpoint_anchoring(self):
        x, y, _ = synthetic_shirley()
        noisy = y+np.random.default_rng(37).normal(0, 0.02, len(y))
        bg = shirley_background(x, noisy)
        self.assertTrue(np.isfinite(bg).all())
        self.assertAlmostEqual(bg[0], noisy[0], places=10)
        self.assertAlmostEqual(bg[-1], noisy[-1], places=10)

    def test_shirley_against_analytic_gaussian_cdf_and_grid_refinement(self):
        # Analytic integrated peak, independent of the implementation's trapezoid rule.
        errors = []
        for points in [501, 1001]:
            x = np.linspace(275, 295, points)
            integral = ndtr((x-285)/0.8)
            background = 5+12*(integral-integral[0])/(integral[-1]-integral[0])
            actual = shirley_background(x, gaussian(x)+background)
            errors.append(np.max(np.abs(actual-background)))
        self.assertLess(errors[0], 1e-3)
        self.assertLess(errors[1], errors[0]/3)

    def test_insufficient_fit_points_and_nonfinite_background(self):
        with self.assertRaises(ValueError):
            fit_peaks(Spectrum([1, 2, 3], [1, 2, 1]))
        with self.assertRaises(ValueError):
            fit_peaks(Spectrum([1, 2, 3, 4], [1, 2, 2, 1]), [PeakSpec('voigt')])
        for background in [np.full_like(self.x, np.nan), np.full_like(self.x, np.inf)]:
            with self.subTest(background=background[0]), self.assertRaises(ValueError):
                fit_peaks(Spectrum(self.x, gaussian(self.x)), background=background)


class KnownDefectRegressionTests(unittest.TestCase):
    """Regression coverage of the five review findings, fixed in V0.2."""

    def test_descending_background_aligns_with_sorted_spectrum(self):
        x, y, bg = synthetic_shirley()
        descending_bg = shirley_background(x[::-1], y[::-1])
        spectrum = Spectrum(x[::-1], y[::-1])
        # A bare array is ambiguous once Spectrum has sorted its input.
        with self.assertRaisesRegex(ValueError, 'background_energy'):
            fit_peaks(spectrum, background=descending_bg)
        fit = fit_peaks(spectrum, background=descending_bg, background_energy=x[::-1])
        np.testing.assert_allclose(fit.corrected, y-bg, atol=1e-5,
            err_msg='Background returned in original order is silently paired with sorted data')

    def test_shirley_large_constant_offset_invariance(self):
        x, y, _ = synthetic_shirley()
        baseline = shirley_background(x, y)
        shifted = shirley_background(x, y+1e8)-1e8
        np.testing.assert_allclose(shifted, baseline, atol=1e-4, rtol=0,
            err_msg='Large DC offset must not degrade peak-scale convergence accuracy')

    def test_duplicate_intensity_headers_require_manual_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'duplicate.csv'
            path.write_text('BE,Intensity,Intensity\n1,10,100\n2,20,200\n3,30,300\n4,40,400\n')
            with self.assertRaises(ValueError, msg='Duplicate intensity headers must not silently choose the first scan'):
                load_spectrum(path)

    def test_explicit_kev_column_not_silently_labelled_ev(self):
        # Before conversion support exists, known incompatible units should be rejected.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'kev.csv'
            x = np.linspace(275, 295, 101)
            pd.DataFrame({'Binding Energy (keV)': x/1000,
                          'Intensity': gaussian(x)}).to_csv(path, index=False)
            with self.assertRaises(ValueError, msg='Manual column selection must not discard known incompatible energy units'):
                load_spectrum(path, energy_column='Binding Energy (keV)')

    def test_bom_before_initial_comment_is_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'bom_comment.csv'
            path.write_text('\ufeff# instrument comment\nBE,Intensity\n3,30\n2,20\n1,10\n', encoding='utf-8')
            # Neither BOM alone nor comment alone fails; their combination does.
            spectrum = load_spectrum(path)
            np.testing.assert_array_equal(spectrum.energy, [1, 2, 3])


if __name__ == '__main__':
    unittest.main()
