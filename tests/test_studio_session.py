"""Portable session tests without importing Qt."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
from scipy.special import voigt_profile
from PIL import Image

from xps_studio.session import import_dataset, compute_fit, apply_fit, save_project, load_project
from xps_studio.exporting import export_bundle


def simulated_frame():
    x = np.linspace(275, 295, 401)
    peak = 100/(.8*np.sqrt(2*np.pi))*np.exp(-.5*((x-285)/.8)**2)
    noise = np.random.default_rng(123).normal(0, .02, len(x))
    return pd.DataFrame({'Binding Energy (eV)': x[::-1], 'Intensity': (peak+noise)[::-1]})


class StudioSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root/'sample.csv'
        self.frame = simulated_frame()
        self.frame.to_csv(self.path, index=False)
        self.dataset = import_dataset(self.path)
        self.dataset.background_mode = 'none'

    def fitted(self):
        self.dataset.add_peak()
        result = compute_fit(self.dataset)
        apply_fit(self.dataset, result)
        return result

    def test_import_keeps_full_original_data_read_only(self):
        np.testing.assert_allclose(self.dataset.spectrum.original_energy, self.frame.iloc[:, 0])
        np.testing.assert_allclose(self.dataset.spectrum.original_intensity, self.frame.iloc[:, 1])
        with self.assertRaises(ValueError):
            self.dataset.spectrum.intensity[0] = 0
        with self.assertRaises(ValueError):
            self.dataset.spectrum.original_intensity[0] = 0

    def test_supported_import_formats_and_manual_columns(self):
        for suffix in ['csv', 'txt', 'xlsx']:
            with self.subTest(suffix=suffix):
                path = self.root/f'manual.{suffix}'
                frame = self.frame.rename(columns={'Binding Energy (eV)': 'E', 'Intensity': 'Y'})
                if suffix == 'xlsx':
                    frame.to_excel(path, index=False)
                else:
                    frame.to_csv(path, index=False, sep='\t' if suffix == 'txt' else ',')
                dataset = import_dataset(path, 'E', 'Y')
                self.assertEqual(dataset.energy_column, 'E')
                self.assertEqual(len(dataset.spectrum.energy), 401)

    def test_roi_fit_uses_copy_and_recovers_gaussian(self):
        original = self.dataset.spectrum.original_intensity.copy()
        self.dataset.fit_range = (281, 289)
        result = self.fitted()
        self.assertAlmostEqual(result.peaks[0]['center_eV'], 285, delta=.01)
        self.assertAlmostEqual(result.peaks[0]['area'], 100, delta=.2)
        self.assertAlmostEqual(result.peaks[0]['fwhm_eV'], 2*np.sqrt(2*np.log(2))*.8, delta=.01)
        self.assertGreater(result.r_squared, .999)
        self.assertEqual(len(result.energy), 161)
        np.testing.assert_array_equal(self.dataset.spectrum.original_intensity, original)

    def test_fixed_parameters_and_fwhm_bounds(self):
        self.dataset.add_peak()
        peak = self.dataset.peaks[0]
        peak.center.value, peak.center.fixed = 285, True
        peak.area.value, peak.area.fixed = 100, True
        peak.fwhm.value, peak.fwhm.minimum, peak.fwhm.maximum = 1.8, 1.7, 2.0
        result = compute_fit(self.dataset)
        self.assertEqual(result.peaks[0]['center_eV'], 285)
        self.assertEqual(result.peaks[0]['area'], 100)
        self.assertTrue(1.7 <= result.peaks[0]['fwhm_eV'] <= 2.0)

    def test_fit_at_fwhm_bound_remains_valid_when_applied_and_saved(self):
        self.dataset.add_peak()
        peak = self.dataset.peaks[0]
        peak.fwhm.value, peak.fwhm.minimum, peak.fwhm.maximum = 2.1, 2.0, 3.0
        result = compute_fit(self.dataset)
        apply_fit(self.dataset, result)
        peak.validate(*self.dataset.fit_range)
        self.assertAlmostEqual(peak.fwhm.value, 2.0, delta=1e-6)
        path = self.root/'bound.json'
        save_project(path, [self.dataset])
        load_project(path)

    def test_voigt_fwhm_and_sigma_gamma_are_distinct(self):
        x = np.linspace(275, 295, 401)
        y = 100*voigt_profile(x-285, .8, .4)
        path = self.root/'voigt.csv'
        pd.DataFrame({'BE': x, 'Intensity': y}).to_csv(path, index=False)
        dataset = import_dataset(path)
        dataset.background_mode = 'none'
        dataset.add_peak('voigt')
        dataset.peaks[0].voigt_ratio = .5
        result = compute_fit(dataset)
        row = result.peaks[0]
        self.assertAlmostEqual(row['sigma_eV'], .8, delta=1e-5)
        self.assertAlmostEqual(row['gamma_eV'], .4, delta=1e-5)
        self.assertAlmostEqual(row['fwhm_eV'], .8*dataset.peaks[0].width_factor, delta=1e-5)
        self.assertAlmostEqual(row['area'], 100, delta=1e-4)

    def test_multiple_peaks_keep_separate_prefixes(self):
        self.dataset.add_peak()
        self.dataset.add_peak('lorentzian')
        self.dataset.peaks[1].center.value = 288
        self.dataset.peaks[1].area.value = 20
        result = compute_fit(self.dataset)
        self.assertEqual(set(result.components), {'p0', 'p1'})
        np.testing.assert_allclose(sum(result.components.values()), result.peak_fit)

    def test_invalid_and_all_fixed_parameters_rejected(self):
        self.dataset.add_peak()
        peak = self.dataset.peaks[0]
        peak.fwhm.minimum = -1
        with self.assertRaises(ValueError):
            compute_fit(self.dataset)
        peak.fwhm.minimum = 1e-6
        peak.center.fixed = peak.fwhm.fixed = peak.area.fixed = True
        with self.assertRaisesRegex(ValueError, '所有参数'):
            compute_fit(self.dataset)

    def test_empty_range_no_peaks_and_constant_signal_rejected(self):
        with self.assertRaisesRegex(ValueError, '添加'):
            compute_fit(self.dataset)
        self.dataset.fit_range = (1, 2)
        with self.assertRaises(ValueError):
            self.dataset.selected()
        path = self.root/'flat.csv'
        pd.DataFrame({'BE': [1, 2, 3, 4, 5], 'Intensity': [0]*5}).to_csv(path, index=False)
        flat = import_dataset(path)
        flat.add_peak()
        with self.assertRaisesRegex(ValueError, '信号变化'):
            compute_fit(flat)

    def test_range_enclosing_but_exceeding_data_is_rejected(self):
        self.dataset.fit_range = (0, 1000)
        with self.assertRaisesRegex(ValueError, '超出'):
            self.dataset.selected()

    def test_confirm_and_undo_restore_fit_and_settings(self):
        result = self.fitted()
        self.dataset.peaks[0].center.value = 284
        self.dataset.background_mode = 'shirley'
        self.dataset.fit_range = (280, 290)
        self.dataset.invalidate()
        self.dataset.undo()
        self.assertAlmostEqual(self.dataset.peaks[0].center.value, result.peaks[0]['center_eV'])
        self.assertEqual(self.dataset.background_mode, 'none')
        self.assertEqual(self.dataset.fit_range, (275, 295))
        np.testing.assert_array_equal(self.dataset.result.peak_fit, result.peak_fit)

    def test_project_roundtrip_restores_results_without_source_file(self):
        result = self.fitted()
        path = self.root/'project.json'
        save_project(path, [self.dataset], 0)
        self.path.unlink()
        datasets, index = load_project(path)
        self.assertEqual(index, 0)
        self.assertEqual(datasets[0].sample_name, 'sample')
        self.assertEqual(datasets[0].peaks[0].kind, 'gaussian')
        np.testing.assert_array_equal(datasets[0].spectrum.original_energy, self.frame.iloc[:, 0])
        np.testing.assert_array_equal(datasets[0].result.peak_fit, result.peak_fit)
        np.testing.assert_array_equal(datasets[0].result.residual, result.residual)
        self.assertAlmostEqual(datasets[0].result.r_squared, result.r_squared)
        self.assertNotIn('NaN', path.read_text())

    def test_multiple_dataset_project_and_current_index(self):
        path = self.root/'multiple.json'
        self.dataset.add_peak()
        other = deepcopy(self.dataset)
        other.sample_name = 'second'
        save_project(path, [self.dataset, other], 1)
        datasets, index = load_project(path)
        self.assertEqual(index, 1)
        self.assertEqual(datasets[1].sample_name, 'second')

    def test_project_invalid_units_versions_and_tampered_result(self):
        self.fitted()
        path = self.root/'bad.json'
        save_project(path, [self.dataset])
        original = json.loads(path.read_text())
        for key, value in [('version', 99), ('energy_unit', 'keV'), ('current_index', 10)]:
            payload = deepcopy(original)
            payload[key] = value
            path.write_text(json.dumps(payload))
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_project(path)
        payload = deepcopy(original)
        payload['datasets'][0]['result']['raw'][0] += 1
        path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, '不一致'):
            load_project(path)

    def test_exports_contain_original_roi_curves_and_metadata(self):
        self.dataset.fit_range = (281, 289)
        result = self.fitted()
        directory = self.root/'export'
        export_bundle(self.dataset, directory)
        self.assertEqual(len(list(directory.iterdir())), 8)
        excel = pd.read_excel(directory/'results.xlsx', sheet_name=None)
        self.assertEqual(set(excel), {'Parameters', 'Original', 'FitCurves', 'Summary'})
        self.assertEqual(len(excel['Original']), 401)
        self.assertEqual(len(excel['FitCurves']), 161)
        curves = pd.read_csv(directory/'curves.csv')
        np.testing.assert_allclose(curves['residual'], result.residual, atol=1e-12)
        np.testing.assert_allclose(curves['total_fit'], curves['background']+curves['p0'])
        metadata = json.loads((directory/'metadata.json').read_text())
        self.assertEqual(metadata['range_min_eV'], 281)
        self.assertIn('background-corrected', metadata['metric_object'])
        with Image.open(directory/'spectrum.png') as image:
            self.assertAlmostEqual(image.info['dpi'][0], 600, delta=.1)
        self.assertIn('<svg', (directory/'spectrum.svg').read_text())
        self.assertTrue((directory/'spectrum.pdf').read_bytes().startswith(b'%PDF'))
        with self.assertRaisesRegex(ValueError, '已存在'):
            export_bundle(self.dataset, directory)


if __name__ == '__main__':
    unittest.main()
