"""PySide6 presentation; all scientific operations live in session/core modules."""
from copy import deepcopy
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QLabel, QLineEdit, QComboBox, QDoubleSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox, QDialog,
    QDialogButtonBox, QFormLayout, QHeaderView,
)

from xps_analysis.io import read_table
from .session import import_dataset, compute_fit, apply_fit, save_project, load_project
from .exporting import export_bundle


class FitWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, dataset):
        super().__init__()
        self.dataset = deepcopy(dataset)

    def run(self):
        try:
            self.succeeded.emit(compute_fit(self.dataset))
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            self.finished.emit()


class ImportDialog(QDialog):
    """Manual column mapping and common text/Excel import overrides."""
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle('数据导入设置（结合能必须为 eV）')
        self.resize(540, 300)
        self.options = {}
        layout = QFormLayout(self)
        self.separator = QComboBox()
        for label, value in [('自动识别', None), ('逗号', ','), ('制表符', '\t'),
                             ('空白分隔', r'\s+'), ('分号', ';')]:
            self.separator.addItem(label, value)
        self.headerless = QCheckBox('无表头（通过列索引选择）')
        self.sheet = QLineEdit('0')
        self.energy = QComboBox()
        self.intensity = QComboBox()
        self.message = QLabel()
        self.message.setWordWrap(True)
        refresh = QPushButton('读取列 / 刷新')
        refresh.clicked.connect(self.refresh)
        layout.addRow('分隔符', self.separator)
        layout.addRow(self.headerless)
        layout.addRow('Excel 表名或从零开始的表序号', self.sheet)
        layout.addRow(refresh)
        layout.addRow('结合能列（eV）', self.energy)
        layout.addRow('信号强度列（保留输入单位）', self.intensity)
        layout.addRow(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.refresh()

    def refresh(self):
        try:
            sheet = self.sheet.text().strip()
            self.options = dict(separator=self.separator.currentData(),
                                header=None if self.headerless.isChecked() else 0,
                                sheet_name=int(sheet) if sheet.isdigit() else sheet)
            frame = read_table(self.path, **self.options)
            for combo in [self.energy, self.intensity]:
                combo.clear()
                combo.addItem('自动识别', None)
                for index, column in enumerate(frame.columns):
                    combo.addItem(f'{index}: {column}', index)
            self.message.setText(f'{len(frame)} 行；请核实选择的是结合能而非动能，单位为 eV。')
        except Exception as error:
            self.message.setText(f'读取失败：{error}')


class MainWindow(QMainWindow):
    fit_completed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle('XPS Analysis Studio — V0.2')
        self.resize(1440, 860)
        self.datasets = []
        self.current_index = -1
        self._loading = False
        self._busy = False
        self._thread = None
        self._worker = None
        self.curves = []
        self.last_error = None
        self._editor_valid = True
        self._range_valid = True
        self.splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(self.splitter)
        self._build_left()
        self._build_plots()
        self._build_right()
        self.splitter.setSizes([230, 710, 500])
        self.setStyleSheet('QGroupBox {font-weight: bold;} QPushButton {padding: 5px;} '
                           'QTableWidget {gridline-color: #ccd3dd;}')
        self.statusBar().showMessage('导入数据开始分析；原始数据保留，所有拟合在副本上运行。')

    @property
    def dataset(self):
        return self.datasets[self.current_index] if 0 <= self.current_index < len(self.datasets) else None

    @staticmethod
    def _button(text, callback, layout):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _build_left(self):
        self.left_panel = QWidget()
        layout = QVBoxLayout(self.left_panel)
        self._button('导入 CSV / TXT / XLSX', self.import_dialog, layout)
        self._button('打开 JSON 项目', self.open_dialog, layout)
        self._button('保存 JSON 项目', self.save_dialog, layout)
        layout.addWidget(QLabel('实验光谱'))
        self.dataset_list = QListWidget()
        self.dataset_list.currentRowChanged.connect(self.select_dataset)
        layout.addWidget(self.dataset_list, 2)
        layout.addWidget(QLabel('样品名称'))
        self.sample_name = QLineEdit()
        self.sample_name.textEdited.connect(self.rename_sample)
        layout.addWidget(self.sample_name)
        self.file_info = QLabel('未选择数据')
        self.file_info.setWordWrap(True)
        self.file_info.setTextFormat(Qt.PlainText)
        layout.addWidget(self.file_info)
        layout.addWidget(QLabel('拟合峰（选择后编辑右侧参数）'))
        self.peak_list = QListWidget()
        self.peak_list.currentRowChanged.connect(self.load_peak_editor)
        layout.addWidget(self.peak_list, 2)
        row = QHBoxLayout()
        self._button('添加峰', self.add_peak, row)
        self._button('删除峰', self.remove_peak, row)
        layout.addLayout(row)
        self.splitter.addWidget(self.left_panel)

    def _build_plots(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        visibility = QHBoxLayout()
        self.visible_boxes = {}
        for key, label in [('raw', '原始'), ('background', '背景'), ('components', '分峰'),
                           ('total', '总拟合'), ('residual', '残差')]:
            box = QCheckBox(label)
            box.setChecked(True)
            box.toggled.connect(self.update_visibility)
            self.visible_boxes[key] = box
            visibility.addWidget(box)
        layout.addLayout(visibility)
        self.plot = pg.PlotWidget(background='w')
        self.plot.setLabel('bottom', '结合能', units='eV')
        self.plot.setLabel('left', '强度（输入单位）')
        self.plot.showGrid(x=True, y=True, alpha=.15)
        self.plot.getViewBox().invertX(True)
        self.plot.addLegend()
        self.region = pg.LinearRegionItem(values=(0, 1), brush=(90, 140, 200, 30))
        self.region.setZValue(-5)
        self.region.sigRegionChangeFinished.connect(self.region_changed)
        self.plot.addItem(self.region)
        self.region.setVisible(False)
        layout.addWidget(self.plot, 4)
        self.residual_plot = pg.PlotWidget(background='w')
        self.residual_plot.setLabel('left', '残差')
        self.residual_plot.setLabel('bottom', '结合能', units='eV')
        self.residual_plot.setXLink(self.plot)
        self.residual_plot.getViewBox().invertX(True)
        self.residual_plot.addLine(y=0, pen=pg.mkPen('#888888'))
        layout.addWidget(self.residual_plot, 1)
        self.metric_label = QLabel('R² / RMSE：尚未拟合；拖动蓝色区域选择拟合能区。')
        self.metric_label.setWordWrap(True)
        layout.addWidget(self.metric_label)
        self.splitter.addWidget(panel)

    def _build_right(self):
        self.right_panel = QWidget()
        self.right_panel.setMinimumWidth(500)
        layout = QVBoxLayout(self.right_panel)
        layout.addWidget(QLabel('拟合设置'))
        self.background_box = QComboBox()
        self.background_box.addItem('Shirley 背景', 'shirley')
        self.background_box.addItem('无背景 / 已扣背景', 'none')
        self.background_box.currentIndexChanged.connect(self.background_changed)
        layout.addWidget(self.background_box)
        range_row = QHBoxLayout()
        self.range_low, self.range_high = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in [self.range_low, self.range_high]:
            spin.setRange(-1e6, 1e6)
            spin.setDecimals(6)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self.range_changed)
            range_row.addWidget(spin)
        layout.addWidget(QLabel('拟合范围：低结合能 / 高结合能（eV）'))
        layout.addLayout(range_row)
        self.model_box = QComboBox()
        for label, kind in [('Gaussian', 'gaussian'), ('Lorentzian', 'lorentzian'), ('Voigt', 'voigt')]:
            self.model_box.addItem(label, kind)
        self.model_box.currentIndexChanged.connect(self.parameters_changed)
        layout.addWidget(self.model_box)
        self.parameter_table = QTableWidget(3, 5)
        self.parameter_table.setHorizontalHeaderLabels(['参数', '初值/结果', '固定', '下限', '上限'])
        self.parameter_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for col in [0, 2]:
            self.parameter_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.parameter_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.parameter_table.setColumnWidth(1, 185)
        self.parameter_table.setMaximumHeight(180)
        self.parameter_widgets = []
        for row, title in enumerate(['峰位 (eV)', 'FWHM (eV)', '峰面积']):
            item = QTableWidgetItem(title)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.parameter_table.setItem(row, 0, item)
            spin = QDoubleSpinBox()
            spin.setDecimals(8)
            spin.setRange(-1e12, 1e12)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self.parameters_changed)
            low, high, fixed = QLineEdit(), QLineEdit(), QCheckBox()
            for widget in [low, high]:
                widget.setMinimumWidth(0)
            low.setPlaceholderText('自动')
            high.setPlaceholderText('自动')
            low.textChanged.connect(self.parameters_changed)
            high.textChanged.connect(self.parameters_changed)
            fixed.toggled.connect(self.parameters_changed)
            for col, widget in [(1, spin), (3, low), (4, high), (2, fixed)]:
                self.parameter_table.setCellWidget(row, col, widget)
            self.parameter_widgets.append((spin, low, high, fixed))
        layout.addWidget(self.parameter_table)
        self.ratio = QDoubleSpinBox()
        self.ratio.setRange(.001, 1000)
        self.ratio.setDecimals(5)
        self.ratio.setValue(.5)
        self.ratio.valueChanged.connect(self.parameters_changed)
        layout.addWidget(QLabel('Voigt γ/σ（拟合时固定比例；FWHM 为近似值）'))
        layout.addWidget(self.ratio)
        self.width_info = QLabel('σ、γ 和峰高将在预览或拟合结果中显示；峰高不等于面积。')
        self.width_info.setWordWrap(True)
        layout.addWidget(self.width_info)
        edit_row = QHBoxLayout()
        self._button('确认参数编辑', self.confirm_edits, edit_row)
        self._button('撤销未确认编辑', self.undo_edits, edit_row)
        layout.addLayout(edit_row)
        self.fit_button = self._button('Fit — 运行拟合', self.run_fit, layout)
        self.results_table = QTableWidget()
        layout.addWidget(self.results_table, 1)
        self._button('导出结果（CSV / Excel / PNG / SVG / PDF）', self.export_dialog, layout)
        self.splitter.addWidget(self.right_panel)

    def error(self, message, modal=False):
        self.last_error = str(message)
        self.statusBar().showMessage(f'提示：{message}')
        if modal:
            QMessageBox.warning(self, '无法完成操作', str(message))

    def import_path(self, path, energy_column=None, intensity_column=None, **options):
        dataset = import_dataset(path, energy_column, intensity_column, **options)
        self.datasets.append(dataset)
        self.dataset_list.addItem(f'{dataset.sample_name} — {Path(dataset.source).name}')
        self.dataset_list.setCurrentRow(len(self.datasets)-1)
        return dataset

    def import_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '导入实验数据', '', 'XPS 数据 (*.csv *.txt *.xlsx)')
        for path in paths:
            try:
                self.import_path(path)
            except Exception as initial_error:
                dialog = ImportDialog(path, self)
                dialog.message.setText(str(initial_error)+'\n请刷新并选择正确数据列；能量必须为 eV。')
                if dialog.exec() == QDialog.Accepted:
                    try:
                        self.import_path(path, dialog.energy.currentData(), dialog.intensity.currentData(), **dialog.options)
                    except Exception as error:
                        self.error(error, modal=True)

    def select_dataset(self, index):
        if self._busy:
            return
        self.current_index = index
        dataset = self.dataset
        if dataset is None:
            return
        self._loading = True
        self.sample_name.setText(dataset.sample_name)
        self.file_info.setText(f'文件：{Path(dataset.source).name}\n列：{", ".join(dataset.columns)}\n'
                               f'结合能：{dataset.energy_column} (eV)\n强度：{dataset.intensity_column}')
        self.background_box.setCurrentIndex(self.background_box.findData(dataset.background_mode))
        self.range_low.setValue(dataset.fit_range[0])
        self.range_high.setValue(dataset.fit_range[1])
        self.region.setBounds((float(dataset.spectrum.energy.min()), float(dataset.spectrum.energy.max())))
        self.region.setRegion(dataset.fit_range)
        self.region.setVisible(True)
        self._loading = False
        self._range_valid = True
        self.refresh_peak_list()
        self.draw(reset_view=True)

    def rename_sample(self, name):
        if self.dataset is not None and not self._loading:
            self.dataset.sample_name = name
            self.dataset_list.item(self.current_index).setText(f'{name} — {Path(self.dataset.source).name}')

    def refresh_peak_list(self, selected=None):
        if selected is None:
            selected = max(self.peak_list.currentRow(), 0)
        self.peak_list.blockSignals(True)
        self.peak_list.clear()
        if self.dataset:
            for i, peak in enumerate(self.dataset.peaks):
                self.peak_list.addItem(f'p{i}: {peak.kind} @ {peak.center.value:.4f} eV')
            self.peak_list.setCurrentRow(min(selected, len(self.dataset.peaks)-1))
        self.peak_list.blockSignals(False)
        self.load_peak_editor(self.peak_list.currentRow())

    def load_peak_editor(self, index):
        self._editor_valid = True
        if self.dataset is None or not 0 <= index < len(self.dataset.peaks):
            self.parameter_table.setEnabled(False)
            return
        self.parameter_table.setEnabled(True)
        peak = self.dataset.peaks[index]
        self._loading = True
        self.model_box.setCurrentIndex(self.model_box.findData(peak.kind))
        self.ratio.setValue(peak.voigt_ratio)
        self.ratio.setEnabled(peak.kind == 'voigt')
        for widgets, par in zip(self.parameter_widgets, [peak.center, peak.fwhm, peak.area]):
            spin, low, high, fixed = widgets
            spin.setValue(par.value)
            low.setText('' if par.minimum is None else str(par.minimum))
            high.setText('' if par.maximum is None else str(par.maximum))
            fixed.setChecked(par.fixed)
        self._loading = False
        self.update_width_info(peak)

    def update_width_info(self, peak):
        try:
            sigma = peak.fwhm.value/peak.width_factor
            gamma = sigma*peak.voigt_ratio if peak.kind == 'voigt' else None
            height = float(peak.evaluate(np.array([peak.center.value]))[0])
            self.width_info.setText(f'σ = {sigma:.6g} eV；γ = {gamma if gamma is not None else "不适用"}\n'
                                    f'峰高 = {height:.6g}（输入强度单位）\n面积单位 = 输入强度单位 × eV')
        except Exception as error:
            self.error(error)

    def parameters_changed(self, *_):
        if self._loading or self._busy or self.dataset is None:
            return
        index = self.peak_list.currentRow()
        if not 0 <= index < len(self.dataset.peaks):
            return
        candidate = deepcopy(self.dataset.peaks[index])
        try:
            candidate.kind = self.model_box.currentData()
            candidate.voigt_ratio = self.ratio.value()
            for widgets, par in zip(self.parameter_widgets, [candidate.center, candidate.fwhm, candidate.area]):
                spin, low, high, fixed = widgets
                par.value = spin.value()
                par.minimum = float(low.text()) if low.text().strip() else None
                par.maximum = float(high.text()) if high.text().strip() else None
                par.fixed = fixed.isChecked()
            candidate.validate(*self.dataset.fit_range)
            self._editor_valid = True
            self.dataset.peaks[index] = candidate
            self.dataset.invalidate()
            self.ratio.setEnabled(candidate.kind == 'voigt')
            self.peak_list.item(index).setText(f'p{index}: {candidate.kind} @ {candidate.center.value:.4f} eV')
            self.update_width_info(candidate)
            self.draw()
        except Exception as error:
            # The last valid session state is preserved; reject this pending editor state.
            self._editor_valid = False
            self.error(error)

    def add_peak(self):
        if self.dataset is None:
            self.error('请先导入实验数据')
            return
        try:
            self.dataset.add_peak(self.model_box.currentData())
            self.refresh_peak_list(len(self.dataset.peaks)-1)
            self.draw()
        except Exception as error:
            self.error(error)

    def remove_peak(self):
        index = self.peak_list.currentRow()
        if self.dataset and 0 <= index < len(self.dataset.peaks):
            self.dataset.peaks.pop(index)
            self.dataset.invalidate()
            self.refresh_peak_list()
            self.draw()

    def confirm_edits(self):
        if self.dataset:
            try:
                self.require_valid_editor()
                for peak in self.dataset.peaks:
                    peak.validate(*self.dataset.fit_range)
                self.dataset.commit()
                self.statusBar().showMessage('当前参数与背景/范围已确认；撤销将返回此状态。')
            except Exception as error:
                self.error(error)

    def undo_edits(self):
        if self.dataset:
            self.dataset.undo()
            self.select_dataset(self.current_index)
            self.statusBar().showMessage('已撤销未确认的参数、背景与能区编辑。')

    def range_changed(self, *_):
        if self._loading or self._busy or self.dataset is None:
            return
        low, high = self.range_low.value(), self.range_high.value()
        if low >= high:
            self._range_valid = False
            self.error('低结合能必须小于高结合能')
            return
        if low < self.dataset.spectrum.energy.min() or high > self.dataset.spectrum.energy.max():
            self._range_valid = False
            self.error('拟合范围不能超出实验数据范围')
            return
        self._range_valid = True
        self.dataset.fit_range = (low, high)
        self.dataset.invalidate()
        self._loading = True
        self.region.setRegion((low, high))
        self._loading = False
        self.draw()

    def region_changed(self):
        if self._loading or self._busy or self.dataset is None:
            return
        low, high = sorted(self.region.getRegion())
        self._range_valid = low < high
        self._loading = True
        self.range_low.setValue(low)
        self.range_high.setValue(high)
        self._loading = False
        self.dataset.fit_range = (low, high)
        self.dataset.invalidate()
        self.draw()

    def background_changed(self, *_):
        if not self._loading and not self._busy and self.dataset:
            self.dataset.background_mode = self.background_box.currentData()
            self.dataset.invalidate()
            self.draw()

    def _curve(self, group, x, y, color, name, residual=False):
        plot = self.residual_plot if residual else self.plot
        curve = plot.plot(x, y, pen=pg.mkPen(color, width=1.6), name=name)
        self.curves.append((group, plot, curve))

    def draw(self, reset_view=False):
        for _, plot, curve in self.curves:
            plot.removeItem(curve)
        self.curves.clear()
        if self.dataset is None:
            return
        ds = self.dataset
        self._curve('raw', ds.spectrum.energy, ds.spectrum.intensity, '#344b63', '原始谱')
        colors = ['#d26a32', '#7865b3', '#329c87', '#bb558a', '#ab9130']
        try:
            selected = ds.selected()
            bg = ds.background(selected) if ds.result is None else ds.result.background
            energy = selected.energy
            self._curve('background', energy, bg, '#88959d', '背景')
            if ds.result:
                for index, (name, values) in enumerate(ds.result.components.items()):
                    self._curve('components', energy, values+bg, colors[index % len(colors)], name)
                self._curve('total', energy, ds.result.total_fit, '#1b83c5', '总拟合')
                self._curve('residual', energy, ds.result.residual, '#344b63', '残差', residual=True)
                self.metric_label.setText(f'R²={ds.result.r_squared:.8g}；RMSE={ds.result.rmse:.8g}（输入强度单位）\n'
                    f'计算对象：扣背景后的数据；范围 {ds.fit_range[0]:.6g}–{ds.fit_range[1]:.6g} eV；逐点等权。')
                self.populate_results(ds.result.peaks)
            else:
                total = bg.copy()
                for index, peak in enumerate(ds.peaks):
                    peak.validate(*ds.fit_range)
                    values = peak.evaluate(energy)
                    total += values
                    self._curve('components', energy, values+bg, colors[index % len(colors)], f'p{index} 预览')
                if ds.peaks:
                    self._curve('total', energy, total, '#1b83c5', '初始模型预览')
                self.metric_label.setText(f'尚未拟合 / 参数已编辑；能区 {ds.fit_range[0]:.6g}–{ds.fit_range[1]:.6g} eV。')
                self.populate_results([])
        except Exception as error:
            self.populate_results([])
            self.metric_label.setText(f'当前设置无法预览：{error}')
            self.error(error)
        self.update_visibility()
        if reset_view:
            self.plot.setXRange(float(ds.spectrum.energy.min()), float(ds.spectrum.energy.max()), padding=.03)
            self.plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)

    def populate_results(self, rows):
        columns = [('peak', '峰'), ('center_eV', '峰位/eV'), ('fwhm_eV', 'FWHM/eV'),
                   ('area', '面积'), ('height', '峰高'), ('sigma_eV', 'σ/eV'), ('gamma_eV', 'γ/eV')]
        self.results_table.setRowCount(len(rows))
        self.results_table.setColumnCount(len(columns))
        self.results_table.setHorizontalHeaderLabels([label for _, label in columns])
        for row, values in enumerate(rows):
            for col, (key, _) in enumerate(columns):
                value = values.get(key)
                text = (f'{value:.7g}' if np.isfinite(value) else '—') if isinstance(value, (int, float)) else str(value or '—')
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.results_table.setItem(row, col, item)
        self.results_table.resizeColumnsToContents()

    def update_visibility(self, *_):
        for group, _, curve in self.curves:
            curve.setVisible(self.visible_boxes[group].isChecked())
        self.residual_plot.setVisible(self.visible_boxes['residual'].isChecked())

    def set_busy(self, busy):
        self._busy = busy
        self.left_panel.setEnabled(not busy)
        self.right_panel.setEnabled(not busy)
        self.region.setMovable(not busy)
        self.statusBar().showMessage('拟合中，请稍候…' if busy else '拟合任务已结束')

    def run_fit(self):
        if self._busy:
            return
        if self.dataset is None:
            self.error('请先导入数据')
            return
        try:
            self.require_valid_editor()
            self.dataset.selected()
            if not self.dataset.peaks:
                raise ValueError('请先添加峰')
            for peak in self.dataset.peaks:
                peak.validate(*self.dataset.fit_range)
        except Exception as error:
            self.error(error)
            return
        self.last_error = None
        self.set_busy(True)
        self._thread = QThread(self)
        self._worker = FitWorker(self.dataset)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.succeeded.connect(self.fit_succeeded)
        self._worker.failed.connect(self.fit_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self.thread_finished)
        self._thread.start()

    def fit_succeeded(self, result):
        apply_fit(self.dataset, result)
        self.refresh_peak_list()
        self.draw()

    def fit_failed(self, message):
        self.error(f'拟合失败：{message}')

    def thread_finished(self):
        self.set_busy(False)
        self._thread.deleteLater()
        self._thread = None
        self._worker = None
        if self.last_error:
            self.statusBar().showMessage(self.last_error)
        self.fit_completed.emit()

    def require_valid_editor(self):
        if not self._editor_valid or not self._range_valid:
            raise ValueError('界面中有尚未修正的非法输入；请修正或撤销编辑，不能使用旧参数代替')

    def save_to(self, path):
        self.require_valid_editor()
        if not self.datasets:
            raise ValueError('没有可保存的数据')
        save_project(path, self.datasets, self.current_index)

    def open_from(self, path):
        datasets, index = load_project(path)
        self.datasets = datasets
        self.dataset_list.blockSignals(True)
        self.dataset_list.clear()
        for ds in datasets:
            self.dataset_list.addItem(f'{ds.sample_name} — {Path(ds.source).name}')
        self.dataset_list.setCurrentRow(index)
        self.dataset_list.blockSignals(False)
        self.select_dataset(index)

    def export_to(self, directory):
        self.require_valid_editor()
        if self.dataset is None:
            raise ValueError('请先导入数据')
        return export_bundle(self.dataset, directory)

    def save_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, '保存项目', '', 'XPS 项目 (*.json)')
        if path:
            try:
                self.save_to(path)
                self.statusBar().showMessage(f'项目已保存：{path}')
            except Exception as error:
                self.error(error, modal=True)

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, '打开项目（替换当前会话）', '', 'XPS 项目 (*.json)')
        if path:
            if self.datasets and QMessageBox.question(self, '打开项目', '将替换当前会话。未保存的修改可能丢失，继续？') != QMessageBox.Yes:
                return
            try:
                self.open_from(path)
            except Exception as error:
                self.error(error, modal=True)

    def export_dialog(self):
        directory = QFileDialog.getExistingDirectory(self, '选择新的结果导出目录')
        if directory:
            try:
                self.export_to(directory)
                self.statusBar().showMessage(f'结果已导出：{directory}')
            except Exception as error:
                self.error(error, modal=True)

    def closeEvent(self, event):
        if self._busy:
            self.error('拟合尚未完成，请等待后台任务结束后关闭窗口')
            event.ignore()
            return
        event.accept()
