# XPS Analysis 第一阶段代码审查报告

审查基线：`516394f`，分支 `feature/xps-analysis-phase1`。
运行环境：Python 3.12.14；numpy 2.3.5、pandas 2.2.3、scipy 1.17.0、
matplotlib 3.10.8、lmfit 1.3.4、openpyxl 3.1.5。

本次仅增加边界测试和审查报告，没有修改应用实现，没有新增专业拟合功能，
没有合并到 main。结论：常规流程有验证依据，但已确认 5 个边界缺陷，
建议修复并重新运行测试后再考虑合并。

## 1. 已确认问题，按影响排序

P1：可能静默输出错误数据或科研指标；P2：特定输入下精度退化或读取失败。

### F1 / P1：外部背景与自动排序的数据可能错位

位置：`xps_analysis/io.py:23`、`xps_analysis/background.py:40`、
`xps_analysis/fitting.py:47`。

`Spectrum` 会将能量、强度配对升序排序；Shirley 返回背景时恢复到调用者的
原始顺序。但 `fit_peaks` 对外部背景只检查长度和有限性，不检查对应能量。
以下自然的调用方式产生错误：

```python
background = shirley_background(descending_energy, descending_intensity)
spectrum = Spectrum(descending_energy, descending_intensity)
fit = fit_peaks(spectrum, background=background)
```

模拟参考：真峰位 285 eV、面积 100、Gaussian σ=0.8，背景从 5 上升到 17。
错位后扣背景数据最大误差为 12；峰位变为 285.3348505 eV，
面积变为 108.2000970，R² 降至 0.5839859。

Shirley 函数本身对降序输入是正确的；目前 CLI 和 README 的流程先创建
Spectrum，再使用其已排序的数组生成背景，因此不触发该问题。

临时安全用法：始终使用 `spectrum.energy` 和 `spectrum.intensity` 计算背景。
建议修复：明确并验证背景坐标契约，或把背景与能量绑定后共同排序。
不能对所有传入背景无条件反转，因为背景也可能已经是升序。

回归测试：`test_descending_background_aligns_with_sorted_spectrum`，失败。

### F2 / P1：手动选择非 eV 列会丢失已知单位信息

位置：`xps_analysis/io.py:52`、`xps_analysis/fitting.py:91`、
`xps_analysis/plotting.py:19`、`xps_analysis/export.py:9`。

自动识别不会将 `Binding Energy (keV)` 当成 eV，但手动指定该列后，程序会
原样使用数值，并将图轴、峰位和 FWHM 标记为 eV。示例：285 eV 峰换成
0.285 keV 后，输出 `center_eV=0.285`、`fwhm_eV=0.001883856`；
面积随横坐标缩放从 100 变成 0.1，导出不保留单位来源。

对 keV 数值的拟合本身没有算错；错误在于把结果标成 eV。未知表头手动读取
也默认依赖用户保证输入是 eV。Counts、CPS、a.u. 不会自动互相转换。

建议修复：在仅支持 eV 的第一阶段，拒绝明确不兼容的单位，明确记录输入
单位要求；后续若支持转换，必须同步处理能量、峰宽和面积单位。

回归测试：`test_explicit_kev_column_not_silently_labelled_ev`，失败。

### F3 / P1：重复列名绕过“歧义必须手动选择”的保护

位置：`xps_analysis/io.py:46`、`xps_analysis/io.py:57`。

输入表头 `BE,Intensity,Intensity` 被 pandas 改名为
`BE,Intensity,Intensity.1`，自动识别仅匹配第一个 Intensity。
两个实验扫描的强度分别为 `[10,20,30,40]` 和 `[100,200,300,400]` 时，
程序不报歧义，静默选择第一组。CSV 和 XLSX 均已复现。

建议修复：保留原始表头的重复信息，或识别 pandas 派生列名并拒绝自动选择；
允许用户通过明确索引选择一个扫描。

回归测试：`test_duplicate_intensity_headers_require_manual_selection`，失败。

### F4 / P2：Shirley 的收敛阈值依赖绝对强度偏移

位置：`xps_analysis/background.py:25`、`xps_analysis/background.py:33`。

停止条件是 `max(abs(candidate-background)) <= tolerance * max(abs(y))`。
给整条谱加常量，本应仅给背景加同样的常量，不改变扣背景后的峰。
目前大常量使停止阈值过宽，产生提前收敛：

| 加入常量 | 减去常量后的背景与原背景的最大差值 |
|---:|---:|
| 1,000 | 0.0000196 |
| 1,000,000 | 0.0266287 |
| 100,000,000 | 3.1402264 |

最后一行是数值压力测试，不代表所有真实谱都会具有这种偏移。它确认了
收敛准则不具有所需的平移稳定性。该例的真实背景阶跃仅为 12。

建议修复：在中心化强度上迭代，用峰/背景变化尺度与绝对误差共同定义阈值，
并检查最终固定点残差。不要仅通过放宽回归测试阈值来隐藏提前停止。

回归测试：`test_shirley_large_constant_offset_invariance`，失败。

### F5 / P2：UTF-8 BOM 与首行注释组合导致读取失败

位置：`xps_analysis/io.py:59`。

文件开始于 `\ufeff# instrument comment\nBE,Intensity\n...` 时，默认分隔符
推断抛出 `_csv.Error: Could not determine delimiter`。
仅有 BOM、仅有首行注释都能读取；它们组合后失败。额外探查显示，显式指定
逗号也不能解决该文件：表头会被错误读为 `Unnamed: 0`。

建议修复：使用明确的 UTF-8 BOM 处理，并在分隔符推断前一致处理注释。
临时处理可在数据副本中去掉 BOM 或首行注释；保留原始实验文件。

回归测试：`test_bom_before_initial_comment_is_readable`，读取异常。

## 2. 已验证的算法和功能

### Shirley 数学与排序

升序结合能下，实现的固定点方程为：

```text
I(E) = ∫[E_low,E] (y(u) - B(u)) du
B(E) = y_low + (y_high-y_low) I(E) / I(E_high)
```

它等价于从另一端积分的端点锚定 Shirley 形式。迭代使用 0.5 阻尼，
梯形积分使用实际能量坐标，而非假定等步长。

已验证升序、降序、随机顺序、非均匀间隔、常量负偏移和反向背景阶跃；
输出恢复到输入顺序。通过已知合成背景恢复测试。
另用 Gaussian 的解析 CDF 独立构造背景，501 点网格最大误差约 0.0006652；
加密到 1001 点后误差降至原来的三分之一以下，符合离散积分精度预期。
首尾等高时返回常量背景，是该端点模型的退化情形。
积分近零或迭代不收敛会报错，而非返回未收敛背景。

限制：首尾点包含峰尾或异常点时会直接影响背景；原实现不验证净峰信号为正、
背景单调性或物理有效性。带符号积分保留负噪声，但不能保证任意强噪声下的
背景都具有物理意义。F1 是跨模块的坐标契约缺陷，F4 是停止准则缺陷。

### 峰型、FWHM 与面积

Gaussian：

```text
G(E) = A / (σ√(2π)) × exp(-(E-μ)²/(2σ²))
FWHM = 2√(2 ln 2)σ
```

Lorentzian：

```text
L(E) = Aσ / (π((E-μ)²+σ²))
FWHM = 2σ
```

Voigt 是归一化 Gaussian 与 Lorentzian 的卷积。通过 SciPy
`voigt_profile` 作定义对照，检查独立 σ、γ 的恢复。
Gaussian 的 σ 为标准差；Lorentzian 的 σ 为半高半宽；Voigt 的 γ 为
Lorentzian 半高半宽，它们不应统称“标准差”。

已检查 lmfit 1.3.4 安装源码；程序正确解除 Voigt 的默认 `gamma=sigma`
约束。Gaussian 和 Lorentzian 的 FWHM 在 lmfit 常数精度内符合解析值。
Voigt 使用如下近似，不是精确的数值半高宽：

```text
FWHM ≈ 1.0692γ + √(0.8664γ² + 5.545083σ²)
```

独立求根找到真实半高位置；γ/σ = 0.001、0.01、0.1、1、10、100 的本次
检查中，最大绝对相对误差约 0.01269%，全部小于 0.03%。该结果仅针对
测试的比例，不作为所有参数的全局误差证明。

全无限区间的独立数值积分与输出 area 一致，area 就是 A。
它不是峰高，也不是测量窗口内的积分。示例 Lorentzian A=100、σ=0.8，
在 μ±10 eV 内的积分约 94.917866，而输出完整峰面积应是 100。
有限窗口尤其会截断 Lorentzian/Voigt 的长尾。

### R²、残差、背景扣除和导出

```text
corrected = raw - background
residual = corrected - peak_fit = raw - (background + peak_fit)
R² = 1 - Σresidual² / Σ(corrected - mean(corrected))²
```

该定义合理，独立重算一致；允许负 R²，常量信号返回 NaN。
R² 分母采用扣背景后的信号，而不是原始信号，应明确该口径，不能将不同
背景或不同能区下的 R² 直接当成同一物理模型质量指标。
不均匀采样时拟合和 R² 按每个点等权，不是按能量区间积分加权。

正常流程只扣一次背景；`total_fit` 只加一次背景。逐点恒等式以及已扣背景
数据使用 `background=None` 的等价性均通过。程序没有记录“已扣背景”状态，
用户把已扣背景数据再配一个背景仍会重复扣除；CLI 应使用 `--background none`。

多峰绘图的每条分量曲线加背景，仅用于原始谱尺度上的显示；这些显示曲线
不能直接相加，否则背景会多算。实际总拟合与 Excel 的峰分量没有此错误。

Excel 的峰表、汇总表、光谱表和残差经过读回验证；PNG 格式、600 dpi
元数据、像素尺寸与降序能量轴均通过原有测试。API 导出可覆盖指定文件，
CLI 会拒绝覆盖已有输出文件。

## 3. 噪声、异常输入和读取边界

| 情形 | 本次验证结果 | 限制 |
|---|---|---|
| 小幅高斯噪声 | 三种峰恢复、Shirley 端点锚定通过 | 不等于强噪声、离群点或泊松噪声验证 |
| 负强度/负噪声 | 保留输入，不裁剪，正峰仍可恢复 | 非负峰面积约束不支持真实负峰 |
| 部分字段缺失、NaN、Inf | 三种文件中的缺失强度及数组非有限值被拒绝 | 不提供自动插值或修补 |
| 重复结合能/形状不匹配 | 明确拒绝 | 不自动合并重复点 |
| 非均匀能量间隔 | Shirley 与拟合坐标正确 | 等权拟合会让密集采样区更有影响 |
| CSV/TXT 分隔符 | 逗号、分号、制表符推断通过；空白分隔显式参数已有测试 | BOM+注释存在 F5；不支持任意仪器说明行 |
| Excel | 默认首表、指定表、无表头和缺失值测试通过 | CLI 无 sheet 选项，API 可以指定；重复表头存在 F3 |
| 列选择 | 名称、索引、中文别名、缺列和越界拒绝通过 | 已知单位可能丢失，见 F2 |

还需注意：代码没有编码和小数符号选项，GBK、区域化小数逗号和厂家多段
导出格式不能视为已支持；空白行可能被 pandas 跳过，并非所有缺失形式
都会报错。当前严格拒绝缺失数值，而不是“自动清洗全部实验异常”。

## 4. 潜在科研解释风险，区别于已确认缺陷

1. 优化器 success 不代表存在可识别的峰。已实际检查全零/常量/全负信号：
   可以返回 success 和 NaN R²。常量 1 的示例得到约 38,041 eV 的 FWHM
   和约 40,493 的面积，只是在用很宽的峰逼近常量，不应当作真实峰结果。
   建议后续增加结果质量警告，不能只用 success 判断科研有效性。
2. 当前使用普通等权最小二乘，没有计数统计权重、离群点鲁棒损失或背景
   不确定度传播。Excel 中 chi_square/reduced_chi_square 是未加权残差指标，
   不具备已按测量标准差归一化的统计卡方含义。
3. 面积按无限域外推，有限能区或重叠峰时参数可能相关或不可辨识。
   目前不导出参数标准误和协方差，也不以缺少 errorbars 作为质量拒绝条件。
4. 光谱/拟合对象里的数组可被后续修改，结果并非不可变快照；调用方应避免
   在拟合后修改它们，或将后续不可变数据设计作为单独改进。
5. 原始单位、背景类型/参数及仪器来源没有完整写入 Excel，复现真实实验
   时应另外记录。现阶段只按输入数值拟合，不提供 Counts/CPS 归一化。

这些风险不通过本次加入新的专业模型来解决。

## 5. 测试充分性与实际运行结果

原有 12 项覆盖了典型文件、合成背景、小噪声单峰、多峰和导出流程，但不充分：
峰型数据和部分 FWHM 参考都来自 lmfit，自洽测试不能独立证明数学定义；
没有覆盖跨模块降序背景、大偏移收敛、重复列名、已知非 eV 单位、BOM 与
注释组合、常量信号、明显负值及更多读取边界。

新增 `tests/test_review_boundaries.py` 共 27 项（若有 subTest 不另算项目数）：
22 项独立/边界验证通过，5 项未解决问题回归测试未通过。
使用解析式、SciPy Voigt、无限域积分、半高求根和 Gaussian CDF 对照，
降低原有“同一库生成再验证”的自洽测试风险。

实际执行：

```bash
cd /workspace/Codex
XDG_CACHE_HOME=/workspace/onboarding/codex-analysis/cache \
MPLCONFIGDIR=/workspace/onboarding/codex-analysis/mplconfig \
/workspace/venvs/codex-analysis/bin/python -m unittest discover -s tests -v
```

当前环境完整日志：`analysis_output/review/tests.log`（本地生成文件，Git 忽略）。
结果：

```text
Ran 39 tests in 6.001s
FAILED (failures=4, errors=1)
```

| 结果 | 项数 |
|---|---:|
| 通过 | 34（原有 12 + 新增 22） |
| 断言失败 | 4（F1、F2、F3、F4） |
| 读取异常 | 1（F5） |
| 跳过 / disabled / expectedFailure | 0 |

完整测试命令退出码为 1。没有将问题标成 expectedFailure、跳过或减弱断言
来让整个套件通过。失败测试表达修复后应达到的安全行为，当前应用保持原样。
所有已列出的测试都实际运行，无未执行测试。

## 6. 真实实验数据仍需验证

本次没有真实实验文件，不能宣称真实 XPS 定量结果已验证。建议以后使用
带仪器单位与元数据的真实谱，比较可信参考分析结果，重点验证：

- 厂家文件编码、额外表头、多扫描列、Excel 合并单元格和采样方向。
- 合理能区与端点选择、强噪声/离群点/峰尾对 Shirley 的影响。
- 峰位校准、长尾外推、多峰相关性及残差结构。
- Counts/CPS 的来源、能量单位、步长和采集时间的实际含义。
- 重复测量下峰位、FWHM、面积的稳定性与测量不确定度。

本次不开发 Co 2p/Ba 3d 的专业约束模型，也不把基础峰型的成功拟合当成
元素识别或化学态结论。

建议顺序：先修复 5 个已确认缺陷，重新运行全部回归测试，再用真实数据
确认上述实验边界，之后由用户决定是否合并。
