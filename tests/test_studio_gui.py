"""Exercise real Qt widgets and worker event delivery in offscreen mode."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import tempfile
import time
import unittest

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent

from xps_studio.window import MainWindow, ImportDialog


class StudioGUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        x = np.linspace(275, 295, 401)
        y = 100/(.8*np.sqrt(2*np.pi))*np.exp(-.5*((x-285)/.8)**2)
        self.path = self.root/'gaussian.csv'
        pd.DataFrame({'BE': x[::-1], 'Intensity': y[::-1]}).to_csv(self.path, index=False)
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        if self.window._busy:
            self.wait_fit()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def import_and_add(self):
        self.window.import_path(self.path)
        self.window.background_box.setCurrentIndex(self.window.background_box.findData('none'))
        self.window.add_peak()

    def wait_fit(self):
        deadline = time.monotonic()+15
        while self.window._busy and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertFalse(self.window._busy, 'GUI fit worker did not finish')
        self.app.processEvents()

    def fit(self):
        spy = QSignalSpy(self.window.fit_completed)
        QTest.mouseClick(self.window.fit_button, Qt.LeftButton)
        self.wait_fit()
        self.assertEqual(spy.count(), 1)
        self.assertIsNotNone(self.window.dataset.result, self.window.last_error)

    def test_startup_three_panels_and_empty_fit_error(self):
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.splitter.count(), 3)
        QTest.mouseClick(self.window.fit_button, Qt.LeftButton)
        self.assertIn('导入', self.window.last_error)

    def test_import_displays_raw_and_switches_datasets(self):
        self.window.import_path(self.path)
        raw = next(curve for group, _, curve in self.window.curves if group == 'raw')
        self.assertEqual(len(raw.getData()[0]), 401)
        self.assertTrue(self.window.plot.getViewBox().state['xInverted'])
        self.assertIn('gaussian.csv', self.window.file_info.text())
        self.window.import_path(self.path)
        self.window.dataset_list.setCurrentRow(0)
        self.assertEqual(self.window.current_index, 0)
        self.assertEqual(self.window.dataset_list.count(), 2)

    def test_manual_column_import(self):
        path = self.root/'manual.txt'
        pd.DataFrame({'E': [3, 2, 1], 'Y': [1, 2, 1]}).to_csv(path, sep='\t', index=False)
        self.window.import_path(path, 'E', 'Y')
        self.assertEqual(self.window.dataset.energy_column, 'E')
        self.assertEqual(len(self.window.dataset.spectrum.energy), 3)

    def test_import_dialog_refresh_and_manual_mapping(self):
        path = self.root/'unknown.txt'
        pd.DataFrame({'E': [3, 2, 1], 'Y': [1, 2, 1]}).to_csv(path, sep='\t', index=False)
        dialog = ImportDialog(str(path), self.window)
        self.assertEqual(dialog.energy.count(), 3)
        dialog.energy.setCurrentIndex(1)
        dialog.intensity.setCurrentIndex(2)
        self.window.import_path(path, dialog.energy.currentData(), dialog.intensity.currentData(), **dialog.options)
        self.assertEqual(self.window.dataset.energy_column, 'E')
        dialog.deleteLater()

    def test_mouse_wheel_zooms_interactive_plot(self):
        self.import_and_add()
        self.app.processEvents()
        before = self.window.plot.getViewBox().viewRange()[0]
        viewport = self.window.plot.viewport()
        position = viewport.rect().center()
        event = QWheelEvent(QPointF(position), QPointF(viewport.mapToGlobal(position)),
                            QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                            Qt.NoScrollPhase, False)
        QApplication.sendEvent(viewport, event)
        self.app.processEvents()
        after = self.window.plot.getViewBox().viewRange()[0]
        self.assertLess(after[1]-after[0], before[1]-before[0])

    def test_parameter_edit_updates_preview_and_undo(self):
        self.import_and_add()
        self.window.confirm_edits()
        before = self.window.dataset.peaks[0].center.value
        spin = self.window.parameter_widgets[0][0]
        spin.setValue(284.5)
        self.assertEqual(self.window.dataset.peaks[0].center.value, 284.5)
        preview = next(curve for group, _, curve in self.window.curves if group == 'components')
        x, y = preview.getData()
        self.assertAlmostEqual(x[np.argmax(y)], 284.5, delta=.06)
        self.window.undo_edits()
        self.assertEqual(self.window.dataset.peaks[0].center.value, before)
        self.assertEqual(spin.value(), before)

    def test_invalid_editor_does_not_fit_using_stale_parameters(self):
        self.import_and_add()
        self.window.confirm_edits()
        self.window.parameter_widgets[1][1].setText('-1')
        self.assertFalse(self.window._editor_valid)
        self.window.run_fit()
        self.assertFalse(self.window._busy)
        self.assertIn('非法输入', self.window.last_error)
        self.window.undo_edits()
        self.assertTrue(self.window._editor_valid)

    def test_interactive_roi_and_visibility(self):
        self.import_and_add()
        self.window.region.setRegion((281, 289))
        self.assertEqual(self.window.dataset.fit_range, (281, 289))
        self.assertEqual(self.window.range_low.value(), 281)
        self.window.visible_boxes['raw'].setChecked(False)
        raw = next(curve for group, _, curve in self.window.curves if group == 'raw')
        self.assertFalse(raw.isVisible())
        self.window.visible_boxes['raw'].setChecked(True)
        self.assertTrue(raw.isVisible())

    def test_fit_button_recovers_parameters_updates_table_and_residual(self):
        self.import_and_add()
        self.window.parameter_widgets[0][0].setValue(284.8)
        self.fit()
        result = self.window.dataset.result
        self.assertAlmostEqual(result.peaks[0]['center_eV'], 285, delta=1e-5)
        self.assertAlmostEqual(result.peaks[0]['area'], 100, delta=1e-4)
        self.assertEqual(self.window.results_table.rowCount(), 1)
        self.assertIn('RMSE=', self.window.metric_label.text())
        residual = next(curve for group, _, curve in self.window.curves if group == 'residual')
        np.testing.assert_allclose(residual.getData()[1], result.residual)

    def test_fixed_parameter_and_illegal_roi(self):
        self.import_and_add()
        self.window.parameter_widgets[0][0].setValue(285)
        self.window.parameter_widgets[0][3].setChecked(True)
        self.fit()
        self.assertEqual(self.window.dataset.result.peaks[0]['center_eV'], 285)
        self.window.range_low.setValue(294)
        self.window.range_high.setValue(290)
        self.window.run_fit()
        self.assertFalse(self.window._busy)
        self.assertIn('非法输入', self.window.last_error)

    def test_model_selection_and_peak_deletion(self):
        self.import_and_add()
        self.window.model_box.setCurrentIndex(self.window.model_box.findData('voigt'))
        self.assertEqual(self.window.dataset.peaks[0].kind, 'voigt')
        self.assertTrue(self.window.ratio.isEnabled())
        self.window.ratio.setValue(.8)
        self.assertEqual(self.window.dataset.peaks[0].voigt_ratio, .8)
        self.window.add_peak()
        self.assertEqual(self.window.peak_list.count(), 2)
        self.window.remove_peak()
        self.assertEqual(self.window.peak_list.count(), 1)

    def test_gui_export_and_project_restore(self):
        self.import_and_add()
        self.fit()
        result = self.window.dataset.result
        self.window.export_to(self.root/'exports')
        self.assertTrue((self.root/'exports'/'results.xlsx').exists())
        project = self.root/'state.json'
        self.window.save_to(project)
        self.window.parameter_widgets[0][0].setValue(284)
        self.assertIsNone(self.window.dataset.result)
        self.window.open_from(project)
        self.assertIsNotNone(self.window.dataset.result)
        np.testing.assert_array_equal(self.window.dataset.result.peak_fit, result.peak_fit)
        self.assertEqual(self.window.results_table.rowCount(), 1)


if __name__ == '__main__':
    unittest.main()
