# Codex

My first Python project for scientific data analysis.

## Features
- XPS spectrum analysis
- Peak fitting
- Scientific visualization

## 第一阶段：XPS 基础分析

支持 CSV、TXT、XLSX 数据读取、列识别、原始光谱绘制、Shirley 背景扣除、
Gaussian / Lorentzian / Voigt 峰拟合，以及 Excel 和 600 dpi PNG 导出。
已有 README 内容保留于上方。

### 安装

已验证 Python 3.12（项目要求 Python >= 3.12）；在项目根目录运行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
```

Windows 激活命令为 `.venv\Scripts\activate`。云环境可直接使用已准备的
`source /workspace/venvs/codex-analysis/bin/activate`。

### 命令行使用

```bash
python -m xps_analysis spectrum.csv --model gaussian --output analysis_output/run1
python -m xps_analysis spectrum.xlsx --model voigt --output analysis_output/run2
python -m xps_analysis spectrum.txt --energy-column "Energy" --intensity-column "Counts" --output analysis_output/run3
python -m xps_analysis headerless.txt --headerless --separator '\s+' --energy-index 0 --intensity-index 1 --output analysis_output/run4
```

默认使用 Shirley 背景；已扣背景的数据使用 `--background none`。
输出 `raw.png`（原始光谱）、`fit.png`（背景、峰分量、总拟合、残差）和
`fit.xlsx`（Peaks、Summary、Spectrum 三张表）。命令行拒绝覆盖已有输出文件。
所有光谱图的结合能轴由高到低显示。

数据要求：至少三个有效数值点，结合能不能重复。数据自动按结合能升序排序，
内部运算与图像轴方向相互独立。CSV/TXT 默认推断分隔符；制表符可用
`--separator '\t'`，空白分隔建议显式设置 `--separator '\s+'`。
默认第一行为表头，允许 `#` 注释行；仪器导出的额外说明行须先清理。
XLSX 默认读取首个工作表，Python API 可用 `sheet_name` 选择其他工作表。

自动识别 `Binding Energy (eV)`、`BE`、`结合能(eV)` 等结合能列，及
`Intensity`、`Intensity (cps)`、`Counts`、`CPS`、`信号强度` 等强度列。
列名大小写及常见标点不影响识别；找不到或存在多个候选列时会报错，
请提供明确的列名或从零开始的列索引，不会静默猜测。

### Python API 与多峰扩展

```python
import matplotlib
matplotlib.use("Agg")  # 无显示器的服务器使用
import matplotlib.pyplot as plt
from xps_analysis import (
    load_spectrum, shirley_background, PeakSpec, fit_peaks,
    plot_spectrum, export_png, export_excel,
)

spectrum = load_spectrum("spectrum.csv")
background = shirley_background(spectrum.energy, spectrum.intensity)
fit = fit_peaks(spectrum, [PeakSpec("gaussian")], background=background)
print(fit.peaks)        # center_eV、fwhm_eV、area
print(fit.r_squared)
print(fit.residual)     # 扣背景数据 - 峰拟合；等于原始数据 - 总拟合
figure = plot_spectrum(spectrum, fit)
export_png(figure, "analysis_output/fit.png")
export_excel(fit, "analysis_output/fit.xlsx")
plt.close(figure)

# 多峰拟合必须为每个峰指定初始峰位；请根据自己的能量区间设置。
# fit = fit_peaks(spectrum, [
#     PeakSpec("voigt", center=780.0, sigma=0.8, area=100, gamma=0.4),
#     PeakSpec("voigt", center=782.0, sigma=0.8, area=60, gamma=0.4),
# ], background=background)
```

Python API 导出函数会写入指定路径，调用方应选择新的目标文件。
所有峰面积为 lmfit 的 amplitude（完整模型在无限区间的积分），并非有限
测量区间的数值积分；面积单位为输入强度单位 × eV。
Gaussian FWHM 为 `2√(2 ln 2)σ`，Lorentzian 为 `2σ`；Voigt 使用 lmfit
提供的 FWHM 近似公式，且允许独立拟合 Gaussian σ 和 Lorentzian γ。
R² 基于扣背景后的整条拟合曲线，常量信号的 R² 为 NaN。

Shirley 算法使用实际能量坐标做梯形积分，首尾点作为背景锚点。
应先选择包围完整峰的合理能量区间；端点包含明显峰尾、弱信号或复杂多峰
可能导致背景偏差或不收敛。积分近零和不收敛会明确报错。
当前不提供能量校准、平滑、自动峰数判断、物理双峰约束或元素指认；
模拟测试通过不能替代真实实验数据的物理审查。

### 项目结构

```text
xps_analysis/
  io.py          # Spectrum 数据结构、文件读取、列识别
  background.py  # Shirley 背景算法
  fitting.py     # PeakSpec、独立峰前缀、lmfit 组合模型、指标
  plotting.py    # 原始/拟合光谱与残差图
  export.py      # Excel 导出
  cli.py         # 命令行流程
tests/
  test_analysis.py  # 固定随机种子的模拟数据与端到端测试
requirements.txt
pyproject.toml
```

后续 Co 2p / Ba 3d 模型可通过 `PeakSpec` 与带 `p0_`、`p1_` 等前缀的组合
模型扩展，并在拟合模块增加自旋轨道间距、面积比、共享峰宽和卫星峰约束；
读取、背景、绘图和导出模块可复用。本阶段多峰接口不包含这些物理约束。

### 自动化测试

无需额外测试框架，在根目录运行：

```bash
MPLBACKEND=Agg python -m unittest discover -s tests -v
```

测试覆盖三种文件格式、手动列选择、无表头数据、错误输入、已知 Shirley
背景恢复、非均匀能量采样、三种带噪声峰模型参数恢复、多峰拟合、
残差、Excel 内容、600 dpi PNG、轴方向和命令行完整流程。
