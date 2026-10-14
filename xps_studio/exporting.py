"""Export validated fit snapshots, full original data and publication figures."""
from pathlib import Path
import json
import pandas as pd
from matplotlib.figure import Figure


def summary(dataset):
    result = dataset.result
    if result is None:
        raise ValueError('请先完成拟合，再导出结果')
    return dict(sample_name=dataset.sample_name, energy_unit='eV',
                area_definition='full-domain integrated peak; intensity units * eV',
                r_squared=result.r_squared, rmse=result.rmse,
                metric_object='background-corrected intensity; equal point weighting',
                range_min_eV=dataset.fit_range[0], range_max_eV=dataset.fit_range[1],
                background=dataset.background_mode,
                voigt_width='approximate FWHM; gamma/sigma ratio fixed during GUI fit')


def figure_for_dataset(dataset):
    summary(dataset)
    result = dataset.result
    fig = Figure(figsize=(8, 7))
    ax, residual_ax = fig.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [3, 1]})
    ax.plot(dataset.spectrum.energy, dataset.spectrum.intensity, '.', markersize=2, label='Raw data')
    ax.plot(result.energy, result.background, label='Background')
    ax.plot(result.energy, result.total_fit, label='Total fit')
    for name, values in result.components.items():
        ax.plot(result.energy, values+result.background, '--', label=name)
    ax.set_ylabel('Intensity (input units)')
    ax.legend()
    residual_ax.plot(result.energy, result.residual)
    residual_ax.axhline(0, color='gray', linewidth=.8)
    residual_ax.set_ylabel('Residual')
    residual_ax.set_xlabel('Binding Energy (eV)')
    ax.set_xlim(dataset.spectrum.energy.max(), dataset.spectrum.energy.min())
    fig.tight_layout()
    return fig


def export_bundle(dataset, directory):
    metadata = summary(dataset)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    names = ['parameters.csv', 'curves.csv', 'raw.csv', 'results.xlsx', 'spectrum.png',
             'spectrum.svg', 'spectrum.pdf', 'metadata.json']
    if any((directory/name).exists() for name in names):
        raise ValueError('输出文件已存在，请选择新的目录，避免覆盖')
    peaks = pd.DataFrame(dataset.result.peaks)
    curves = dataset.result.frame()
    raw = pd.DataFrame({'binding_energy_eV': dataset.spectrum.original_energy,
                        'raw_intensity': dataset.spectrum.original_intensity})
    peaks.to_csv(directory/'parameters.csv', index=False, encoding='utf-8-sig')
    curves.to_csv(directory/'curves.csv', index=False, encoding='utf-8-sig')
    raw.to_csv(directory/'raw.csv', index=False, encoding='utf-8-sig')
    with pd.ExcelWriter(directory/'results.xlsx', engine='openpyxl') as writer:
        peaks.to_excel(writer, sheet_name='Parameters', index=False)
        raw.to_excel(writer, sheet_name='Original', index=False)
        curves.to_excel(writer, sheet_name='FitCurves', index=False)
        pd.DataFrame([metadata]).to_excel(writer, sheet_name='Summary', index=False)
    figure = figure_for_dataset(dataset)
    for suffix in ['png', 'svg', 'pdf']:
        figure.savefig(directory/f'spectrum.{suffix}', format=suffix, dpi=600)
    (directory/'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2,
                                                    allow_nan=False), encoding='utf-8')
    return directory
