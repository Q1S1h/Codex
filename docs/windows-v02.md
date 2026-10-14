# XPS Analysis Studio V0.2 — Windows 使用指南

## 安装和启动

推荐 Windows 10/11、Python 3.12 **64 位**。从 Python 官网安装 Python 时
勾选 Python Launcher。下载本分支源代码或克隆仓库后，在项目根目录运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m xps_studio
```

不需要激活 PowerShell 脚本或修改执行策略。PySide6/PyQtGraph 和科学计算
依赖均列于根目录 `requirements.txt`。首次安装需要访问 Python 包仓库。
也可双击 `install_windows.cmd` 完成同样的安装，再双击 `run_studio.cmd`。
如果没有 `py` 命令，可用已安装的 Python 3.12 路径替换 `py -3.12`。
请避免将仓库放在只读目录；更新版本前先保存 JSON 项目。

安装为 editable 项目后也可以运行 `xps-studio`；命令行 V0.1 接口
`python -m xps_analysis` 仍保留。软件是原生 Qt 桌面窗口，不启动 Web 服务。

这些 Windows 命令/脚本尚未在真实 Windows 上执行；云端检查的是 Linux
上的相同 Python 代码和依赖，不构成 Windows 10/11 的兼容性认证。
本阶段没有生成正式 EXE 或安装包。

## 三栏界面

左栏：实验数据列表、文件名和全部列名、结合能/强度列映射、样品名称、
拟合峰列表、添加/删除峰、打开/保存 JSON 项目。

中栏：PyQtGraph 光谱和残差图。结合能从高到低显示，滚轮缩放，左键拖动
平移；拖动蓝色拟合区域或其两条边界选择能区。上方复选框独立控制原始谱、
背景、分峰、总拟合、残差的显示。面板分隔条可拖动改变宽度。
拟合区域始终覆盖在主图上，不会改变原始数据。

右栏：背景类型、精确的能量上下限、峰型、峰位/FWHM/面积值及上下限、
固定开关、Voigt 比例、确认/撤销、Fit、结果表和结果导出。

## 数据导入

点击“导入 CSV / TXT / XLSX”，可同时选择多个文件。导入成功后立即显示
原始光谱；点击左侧列表切换光谱，每条光谱独立保留范围、背景、峰和结果。
样品名称可编辑，原始文件名与列映射仍保留。

默认识别 Binding Energy / BE / 结合能 和 Intensity / Counts / CPS 等列。
遇到无表头、歧义或非常规列名，弹出手动映射窗口：

1. 选择分隔符、是否无表头和 Excel 工作表（名字或从零开始的序号）。
2. 点击“读取列 / 刷新”。
3. 选择对应的结合能列和强度列，点击确定。

能量必须是 **结合能 eV**。明确的 keV/MeV/J/动能列会被拒绝，不进行默默
换算。无单位的手动列要求使用者事先确认 eV。强度维持输入单位，不会把
Counts 转成 CPS 或对采集时间自动归一化。缺失数值、Inf、重复能量会报错，
不会自动插值、丢弃异常点或覆盖原始实验文件。

UTF-8 和 UTF-8 BOM 可读取；逗号、制表符、分号可推断，空白分隔可手动设置。
不支持任意厂家专属多段格式、GBK 或区域小数逗号；可先导出一个标准表格副本。

## 拟合步骤

1. 导入光谱，选取完整包围待拟合峰的合理能区。
2. 选择 Shirley 背景；数据已经扣过背景时选择“无背景 / 已扣背景”。
3. 点击“添加峰”，选择 Gaussian、Lorentzian 或 Voigt。
4. 调整峰位、FWHM、面积初始值。修改有效值后预览曲线同步更新。
5. 下限/上限留空表示自动范围：峰位限定在 ROI 内，宽度为正，面积非负。
   手动上下限必须递增、包含当前值；勾选“固定”会让该参数不参与优化。
6. 多个峰分别设置初始峰位与面积，避免都落在同一个峰上。
7. 点击 Fit。在后台 Qt 线程运行原有 lmfit 核心，拟合期间禁止修改数据
   和参数；完成后更新参数、结果表、分峰/总拟合和残差。
8. 对于失败、无峰、空能区、没有信号变化或全部参数固定的情况，状态栏
   提供提示，不返回伪成功结果。非法编辑不会偷偷使用旧参数运行 Fit。

“确认参数编辑”保存一个撤销基线；“撤销未确认编辑”恢复最后确认的峰参数、
能区、背景和有效结果。成功拟合也成为一个新的撤销基线。
编辑参数、能区或背景后旧拟合结果立即失效，需要重新 Fit 后导出结果。
项目保存的是当前有效参数；打开项目时它们成为新的确认基线。

## 峰参数的科学定义

峰面积是 lmfit 的 amplitude，即归一化峰型在**整个无限能量区间**的积分。
单位是输入强度单位 × eV；不是峰高，也不是有限 ROI 的数值积分。
界面独立显示峰高和面积。

Gaussian 的 σ 是标准差，FWHM ≈ 2.35482σ。
Lorentzian 的 σ 是半高半宽，FWHM = 2σ。

Voigt 的 Gaussian σ 和 Lorentzian γ 不同。本 GUI 为稳定的 MVP 采用
`r = γ/σ`，用户可设置 r，**拟合时固定 r**，拟合一个宽度自由度：

```text
FWHM ≈ σ × [1.0692r + √(0.8664r² + 5.545083)]
γ = rσ
```

右侧 FWHM 初值、上下限、固定开关针对该近似 FWHM；界面与导出同时保留
σ 和 γ。本 GUI 暂不提供 σ、γ 完全独立的双宽度优化；核心 Python API
仍支持独立 σ、γ。固定 γ/σ 是通用宽度参数化，不包含元素专业约束模板。

Shirley 复用原有端点锚定方程，支持升序、降序和非均匀间隔；迭代在扣掉
常量偏移后的数据上进行，避免大偏移放宽停止阈值。首尾点决定背景，
不能仅凭收敛就认为端点选择具有物理合理性。

R² 和 RMSE 的对象是**所选 ROI 内扣背景后的数据**，使用逐点等权残差：

```text
residual = raw - background - sum(peaks)
R² = 1 - sum(residual²) / sum((corrected - mean(corrected))²)
RMSE = sqrt(mean(residual²))
```

界面及导出元数据注明范围、背景和指标对象。原始数组为只读副本；ROI、
背景和拟合使用新的数组，不会改动原始数据。多峰图中分量加背景仅用于
原始强度尺度上的显示，不应把这些显示曲线再次直接相加。

## 保存项目与导出

保存 JSON 项目会嵌入所有光谱的完整原始能量/强度、样品/源文件信息、
峰型和参数值/上下限/固定状态、ROI、背景设置、当前光谱索引以及拟合结果。
不用原始文件仍可恢复曲线和指标；不会在打开项目时偷偷重新拟合。
载入时检查版本、eV 单位、数组长度/有限性及结果与当前设置的一致性。
格式使用普通 JSON，不执行 pickle。当前版本号为 2，不兼容未声明版本的
任意 JSON。视图缩放、面板宽度与曲线显隐暂不作为项目状态保存。

“导出结果”选择一个新的目录，输出：

| 文件 | 内容 |
|---|---|
| parameters.csv | 各峰的峰位、FWHM、面积、峰高、σ、γ |
| curves.csv | ROI 内原始数据、背景、扣背景数据、分峰、总拟合和残差 |
| raw.csv | 全部原始点，保留原始采集顺序 |
| results.xlsx | Parameters、Original、FitCurves、Summary 四张表 |
| spectrum.png | 默认 600 dpi，全部科研曲线与残差 |
| spectrum.svg / spectrum.pdf | 矢量图 |
| metadata.json | 样品、单位、面积定义、背景、范围、R²/RMSE 对象 |

导出图使用完整原始谱及 ROI 内拟合，包含所有科研曲线，不受交互显示开关
影响。已存在上述文件时拒绝覆盖。保存项目通过文件选择器允许另存或覆盖
用户指定的项目文件；原始实验文件始终不会被写入。

## 模拟数据和测试

在项目根目录生成演示数据：

```powershell
.\.venv\Scripts\python.exe examples\create_demo.py
```

导入 `analysis_output\demo_v02\gaussian.csv`。该模拟峰的真实峰位为
285 eV、Gaussian σ=0.8 eV、FWHM≈1.883856 eV、面积=100 cps·eV，
同时包含 Shirley 背景和固定随机种子的噪声。TXT/XLSX 副本一同生成。
文件已存在时脚本拒绝覆盖。

自动测试：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m xps_studio --smoke-test
Remove-Item Env:\QT_QPA_PLATFORM
.\.venv\Scripts\python.exe -m xps_studio
```

启动真实 Windows 界面前移除 `QT_QPA_PLATFORM=offscreen`，否则窗口不可见。
offscreen 测试不能代替 Windows 本机操作，请按 `docs/v02-validation.md`
的本机清单核验缩放、拖动、字体、路径和真实数据。

## MVP 限制与后续工作

- 尚无 Windows 10/11 原生测试、正式 EXE、打包安装或签名。
- 拟合不能取消；拟合中关闭窗口会被阻止，等待任务完成即可关闭。
- 文件读取、预览背景和高分辨率导出仍在 GUI 主线程执行，超大数据文件
  可能短暂阻塞界面；拟合本身在后台线程。
- 每个数据集仅有一个确认/撤销基线，没有多级撤销、批量拟合或操作历史。
- 请在关闭前主动保存项目；当前没有自动保存及关闭时未保存提醒。
- 无能量校准、自动找峰、鲁棒/加权拟合、误差传播或元素识别。
- 不含 Co 2p / Ba 3d 专业双峰、卫星峰或物理约束模板。
- 真实实验数据的端点、峰数、物理峰型与定量可靠性仍需科研人员判断。
