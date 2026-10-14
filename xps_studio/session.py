"""Qt-independent data, parameter, fitting and portable project state."""
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import math

import numpy as np
import pandas as pd
from lmfit.models import GaussianModel, LorentzianModel, VoigtModel

from xps_analysis import Spectrum, PeakSpec, fit_peaks, shirley_background
from xps_analysis.io import read_table, spectrum_from_table, _column

MODELS = {'gaussian': GaussianModel, 'lorentzian': LorentzianModel, 'voigt': VoigtModel}


@dataclass
class Parameter:
    value: float
    minimum: float | None = None
    maximum: float | None = None
    fixed: bool = False

    def bounds(self, default_min, default_max):
        low = default_min if self.minimum is None else self.minimum
        high = default_max if self.maximum is None else self.maximum
        if ((self.minimum is not None and not math.isfinite(self.minimum))
                or (self.maximum is not None and not math.isfinite(self.maximum))
                or not math.isfinite(self.value) or math.isnan(low) or math.isnan(high)
                or low >= high or not low <= self.value <= high):
            raise ValueError('参数值必须有限，且位于严格递增的上下限内')
        return low, high


@dataclass
class Peak:
    kind: str
    center: Parameter
    fwhm: Parameter
    area: Parameter
    voigt_ratio: float = 0.5

    @property
    def width_factor(self):
        if self.kind == 'gaussian':
            # Use the exact expression precision exported by the installed lmfit,
            # so a width fitted at a bound stays inside that same GUI bound.
            return GaussianModel().make_params(sigma=1)['fwhm'].value
        if self.kind == 'lorentzian':
            return 2.0
        if self.kind == 'voigt' and math.isfinite(self.voigt_ratio) and self.voigt_ratio > 0:
            return 1.0692*self.voigt_ratio+np.sqrt(0.8664*self.voigt_ratio**2+5.545083)
        raise ValueError('峰型非法，或 Voigt γ/σ 比例不是正数')

    def validate(self, low, high):
        if self.kind not in MODELS:
            raise ValueError('未知峰型')
        cmin, cmax = self.center.bounds(low, high)
        if cmin < low or cmax > high:
            raise ValueError('峰位上下限必须位于拟合能区内')
        wmin, _ = self.fwhm.bounds(1e-6, np.inf)
        amin, _ = self.area.bounds(0, np.inf)
        if wmin <= 0 or amin < 0 or self.area.value < 0:
            raise ValueError('FWHM 必须为正，峰面积不能为负')
        _ = self.width_factor

    def settings(self, index, low, high):
        self.validate(low, high)
        factor = self.width_factor
        settings = {}
        for name, par, div, fallback in [
            ('center', self.center, 1, (low, high)),
            ('sigma', self.fwhm, factor, (1e-6, np.inf)),
            ('amplitude', self.area, 1, (0, np.inf)),
        ]:
            lo, hi = par.bounds(*fallback)
            settings[f'p{index}_{name}'] = dict(value=par.value/div, min=lo/div,
                                               max=hi/div, vary=not par.fixed)
        if self.kind == 'voigt':
            settings[f'p{index}_gamma'] = dict(expr=f'{self.voigt_ratio!r}*p{index}_sigma')
        return settings

    def evaluate(self, energy):
        sigma = self.fwhm.value/self.width_factor
        kwargs = dict(x=energy, center=self.center.value, amplitude=self.area.value, sigma=sigma)
        if self.kind == 'voigt':
            kwargs['gamma'] = sigma*self.voigt_ratio
        return MODELS[self.kind]().eval(**kwargs)

    @classmethod
    def from_dict(cls, data):
        return cls(data['kind'], *(Parameter(**data[key]) for key in ['center', 'fwhm', 'area']),
                   voigt_ratio=data.get('voigt_ratio', 0.5))


@dataclass
class Result:
    energy: np.ndarray
    raw: np.ndarray
    background: np.ndarray
    components: dict
    peak_fit: np.ndarray
    peaks: list
    r_squared: float | None
    rmse: float
    settings: dict

    @property
    def residual(self):
        return self.raw-self.background-self.peak_fit

    @property
    def total_fit(self):
        return self.background+self.peak_fit

    def frame(self):
        return pd.DataFrame(dict(binding_energy_eV=self.energy, raw_intensity=self.raw,
                                 background=self.background, corrected=self.raw-self.background,
                                 peak_fit=self.peak_fit, total_fit=self.total_fit,
                                 residual=self.residual, **self.components))

    def to_dict(self):
        data = asdict(self)
        for key in ['energy', 'raw', 'background', 'peak_fit']:
            data[key] = data[key].tolist()
        data['components'] = {key: values.tolist() for key, values in self.components.items()}
        # Non-Voigt gamma is undefined, represented by JSON null, not NaN.
        data['peaks'] = [{key: (None if isinstance(value, float) and not math.isfinite(value) else value)
                          for key, value in row.items()} for row in data['peaks']]
        return data

    @classmethod
    def from_dict(cls, data):
        data = deepcopy(data)
        spectrum = Spectrum(data['energy'], data['raw'])
        if spectrum.was_reordered:
            raise ValueError('项目拟合结果必须按能量升序排列')
        for key in ['energy', 'raw', 'background', 'peak_fit']:
            data[key] = np.asarray(data[key], dtype=float)
        data['components'] = {key: np.asarray(value, dtype=float) for key, value in data['components'].items()}
        for array in [data['background'], data['peak_fit'], *data['components'].values()]:
            if array.shape != spectrum.energy.shape or not np.isfinite(array).all():
                raise ValueError('项目拟合数组损坏')
        if not np.allclose(sum(data['components'].values()), data['peak_fit'], atol=1e-8):
            raise ValueError('项目分峰与总峰拟合不一致')
        residual = data['raw']-data['background']-data['peak_fit']
        data['rmse'] = float(np.sqrt(np.mean(residual**2)))
        sst = np.sum((data['raw']-data['background']-np.mean(data['raw']-data['background']))**2)
        data['r_squared'] = float(1-np.sum(residual**2)/sst) if sst > 0 else None
        return cls(**data)


@dataclass
class Dataset:
    spectrum: Spectrum
    source: str
    sample_name: str
    columns: list
    energy_column: str
    intensity_column: str
    fit_range: tuple
    background_mode: str = 'shirley'
    peaks: list = field(default_factory=list)
    result: Result | None = None
    _checkpoint: dict | None = field(default=None, repr=False)

    def selected(self):
        low, high = self.fit_range
        if not np.isfinite([low, high]).all() or low >= high:
            raise ValueError('拟合能区必须是有效的递增上下限')
        if low < self.spectrum.energy[0] or high > self.spectrum.energy[-1]:
            raise ValueError('拟合能区不能超出原始数据范围')
        mask = (self.spectrum.energy >= low) & (self.spectrum.energy <= high)
        return Spectrum(self.spectrum.energy[mask], self.spectrum.intensity[mask])

    def background(self, selected=None):
        selected = self.selected() if selected is None else selected
        if self.background_mode == 'none':
            return np.zeros_like(selected.intensity)
        if self.background_mode != 'shirley':
            raise ValueError('未知背景类型')
        return shirley_background(selected.energy, selected.intensity)

    def invalidate(self):
        self.result = None

    def commit(self):
        self._checkpoint = deepcopy(dict(peaks=self.peaks, fit_range=self.fit_range,
                                         background_mode=self.background_mode, result=self.result))

    def undo(self):
        if self._checkpoint is not None:
            for key, value in deepcopy(self._checkpoint).items():
                setattr(self, key, value)

    def add_peak(self, kind='gaussian'):
        selected = self.selected()
        bg = self.background(selected)
        signal = selected.intensity-bg
        center = float(selected.energy[np.argmax(signal)])
        width = float(np.ptp(selected.energy)/10)
        area = max(float(np.trapezoid(np.maximum(signal, 0), selected.energy)), 1.0)
        self.peaks.append(Peak(kind, Parameter(center), Parameter(width, 1e-6), Parameter(area, 0)))
        self.invalidate()

    def settings_dict(self):
        return dict(fit_range=list(self.fit_range), background_mode=self.background_mode,
                    peaks=[asdict(peak) for peak in self.peaks])


def import_dataset(path, energy_column=None, intensity_column=None, **options):
    table = read_table(path, **options)
    ec, ic = _column(table, energy_column, 'energy'), _column(table, intensity_column, 'intensity')
    spectrum = spectrum_from_table(table, energy_column, intensity_column)
    dataset = Dataset(spectrum, str(Path(path).resolve()), Path(path).stem,
                      [str(col) for col in table.columns], str(ec), str(ic),
                      (float(spectrum.energy[0]), float(spectrum.energy[-1])))
    dataset.commit()
    return dataset


def compute_fit(dataset):
    """Read a detached dataset; return a snapshot without changing raw data or GUI state."""
    if not dataset.peaks:
        raise ValueError('请先添加至少一个拟合峰')
    selected = dataset.selected()
    bg = dataset.background(selected)
    settings, specs = {}, []
    for index, peak in enumerate(dataset.peaks):
        settings.update(peak.settings(index, *dataset.fit_range))
        sigma = peak.fwhm.value/peak.width_factor
        specs.append(PeakSpec(peak.kind, center=peak.center.value, sigma=sigma,
                              area=max(peak.area.value, 1e-12),
                              gamma=sigma*peak.voigt_ratio if peak.kind == 'voigt' else None))
    if not any(value.get('vary', False) for value in settings.values()):
        raise ValueError('所有参数均已固定；请至少释放一个参数后再拟合')
    if np.ptp(selected.intensity-bg) <= np.finfo(float).eps*max(1., np.max(np.abs(selected.intensity))):
        raise ValueError('所选能区没有可拟合的信号变化')
    fit = fit_peaks(selected, specs, background=bg, background_energy=selected.energy,
                    parameter_settings=settings)
    record = Result(selected.energy.copy(), selected.intensity.copy(), bg.copy(),
                    {key.rstrip('_'): value.copy() for key, value in fit.model_result.eval_components().items()},
                    fit.model_result.best_fit.copy(), fit.peaks.to_dict('records'),
                    fit.r_squared if math.isfinite(fit.r_squared) else None, fit.rmse,
                    dataset.settings_dict())
    return record


def apply_fit(dataset, result):
    dataset.result = result
    for peak, row in zip(dataset.peaks, result.peaks):
        peak.center.value = row['center_eV']
        peak.fwhm.value = row['fwhm_eV']
        peak.area.value = row['area']
    # Snapshot corresponds to displayed fitted parameters, not the old guesses.
    result.settings = dataset.settings_dict()
    dataset.commit()


def save_project(path, datasets, current_index=0):
    payload = dict(format='XPS Analysis Studio', version=2, energy_unit='eV',
                   current_index=current_index, datasets=[])
    for dataset in datasets:
        entry = dict(source=dataset.source, sample_name=dataset.sample_name, columns=dataset.columns,
                     energy_column=dataset.energy_column, intensity_column=dataset.intensity_column,
                     energy=dataset.spectrum.original_energy.tolist(),
                     intensity=dataset.spectrum.original_intensity.tolist(), **dataset.settings_dict(),
                     result=dataset.result.to_dict() if dataset.result is not None else None)
        payload['datasets'].append(entry)
    # Encode fully before touching the destination; no NaN/Infinity or executable pickle.
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
    path = Path(path)
    temporary = path.with_name(path.name+'.tmp')
    try:
        temporary.write_text(encoded, encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_project(path):
    def reject_constant(value):
        raise ValueError(f'项目含非法数值: {value}')
    payload = json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=reject_constant)
    if payload.get('format') != 'XPS Analysis Studio' or payload.get('version') != 2 or payload.get('energy_unit') != 'eV':
        raise ValueError('不支持的项目格式、版本或能量单位')
    datasets = []
    for entry in payload['datasets']:
        spectrum = Spectrum(entry['energy'], entry['intensity'])
        dataset = Dataset(spectrum, entry['source'], entry['sample_name'], entry['columns'],
                          entry['energy_column'], entry['intensity_column'], tuple(entry['fit_range']),
                          entry['background_mode'], [Peak.from_dict(peak) for peak in entry['peaks']])
        dataset.selected()
        for peak in dataset.peaks:
            peak.validate(*dataset.fit_range)
        if dataset.background_mode not in {'none', 'shirley'}:
            raise ValueError('项目背景类型非法')
        if entry.get('result') is not None:
            result = Result.from_dict(entry['result'])
            selected = dataset.selected()
            if (not np.array_equal(result.energy, selected.energy)
                    or not np.array_equal(result.raw, selected.intensity)
                    or result.settings != dataset.settings_dict()):
                raise ValueError('项目拟合结果与数据或参数不一致')
            dataset.result = result
        dataset.commit()
        datasets.append(dataset)
    index = payload['current_index']
    if not datasets or not isinstance(index, int) or not 0 <= index < len(datasets):
        raise ValueError('项目没有光谱或当前光谱索引无效')
    return datasets, index
