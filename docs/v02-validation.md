# V0.2 开发与验证记录

## 分支与范围

开发分支：`feature/xps-analysis-gui-v02`。
起点：`feature/xps-analysis-phase1` 的 `f7d70f8`，包含第一阶段完整实现及审查测试。
开始时远程 main 仍是 `e140682`，只有 README，因此没有从 main 丢弃既有功能。
本版本未合并 main，没有 Co 2p/Ba 3d 专业模板，也没有正式 EXE。

## 项目结构

```text
xps_analysis/                  # 现有科学计算核心，保留 CLI
  io.py                        # 表格、列识别、只读光谱与原始采集顺序
  background.py                # 原端点锚定 Shirley，修复偏移收敛问题
  fitting.py                   # 原 lmfit 模型；可选参数约束及背景坐标契约
  plotting.py, export.py, cli.py
xps_studio/                    # 新增桌面程序
  session.py                   # 不依赖 Qt：数据、参数、ROI、撤销、拟合快照、JSON
  exporting.py                 # CSV/Excel/PNG/SVG/PDF 与元数据
  window.py                    # PySide6 三栏 UI、PyQtGraph、手动导入、后台 Fit
  app.py, __main__.py           # 桌面入口和有限时长启动检查
tests/
  test_analysis.py             # 原有 12 项
  test_review_boundaries.py    # 审查扩展 27 项，五个缺陷现在回归通过
  test_studio_session.py       # 新增 15 项，不依赖 Qt
  test_studio_gui.py           # 新增 12 项，实际 Qt 控件/线程/事件
examples/create_demo.py        # 带噪声、Shirley 背景的三格式模拟数据
requirements.txt, pyproject.toml
install_windows.cmd, run_studio.cmd
docs/windows-v02.md            # Windows 安装和使用说明
docs/code-review-phase1.md     # 保留的历史审查报告，状态以本文为准
```

GUI 没有重写峰型、最小二乘优化或 Shirley 方程。预览调用 lmfit 模型，
运行 Fit 调用 `xps_analysis.fit_peaks`，状态与 GUI 分开。

## 第一阶段审查问题的处理

| 原问题 | V0.2 修复与验证 |
|---|---|
| 外部背景与降序光谱错位 | 新增 `background_energy`，按明确坐标对齐；重排过的数据禁止无坐标背景。CLI/文档同步传入坐标；回归验证拒绝歧义和正确对齐 |
| keV 手动列标为 eV | 明确的非 eV/动能标签拒绝读取，不静默换算；没有单位的表头仍由用户保证 eV |
| 重复列自动选择 | 识别 pandas `.1` 等派生表头的候选歧义，要求明确索引或列名 |
| 大偏移放宽 Shirley 阈值 | 在端点中心化的强度上迭代，结束时恢复偏移；大常量平移回归通过 |
| BOM + 首行注释读取失败 | 采用 utf-8-sig，在注释与分隔符解析前去除 BOM；组合回归通过 |

背景坐标契约属于有意的安全 API 变更。不能自动猜测一个裸背景数组属于
原始顺序还是已排序顺序，因此以明确坐标取代原先的静默配对。
原有 12 项测试均保留。降序外部背景回归增加了拒绝歧义的断言，并用明确坐标
检查原来的恢复精度；没有跳过、标记 expectedFailure 或放宽失败条件。

## 当前实例的实测结果

环境：Linux 云机器，Python 3.12.14；PySide6 6.10.2、PyQtGraph 0.14.0，
科学计算依赖版本见 requirements.txt。

实际命令：

```bash
cd /workspace/Codex
QT_QPA_PLATFORM=offscreen \
XDG_CACHE_HOME=/workspace/onboarding/codex-analysis/cache \
MPLCONFIGDIR=/workspace/onboarding/codex-analysis/mplconfig \
/workspace/venvs/codex-analysis/bin/python -m unittest discover -s tests -v
```

最终结果：

```text
Ran 66 tests in 10.843s
OK
```

| 测试类别 | 通过 | 失败/异常/跳过 |
|---|---:|---:|
| 第一阶段及审查回归 | 39 | 0 |
| 会话、约束、项目与导出 | 15 | 0 |
| Qt GUI、线程和事件 | 12 | 0 |
| 合计 | 66 | 0 |

完整日志位于当前实例 `analysis_output/v02/all-tests.log`，属于被 Git 忽略的
运行产物。另有先行核心检查日志 `analysis_output/v02/core-tests.log`。

已实际安装 editable V0.2 包；运行 `pip check` 检查依赖；运行
`QT_QPA_PLATFORM=offscreen xps-studio --smoke-test` 验证安装后的入口。
启动显示窗口、事件循环运行约 800 ms 后正常退出，返回码 0。
offscreen 插件的 `propagateSizeHints()` 提示属于平台能力提示，不是测试失败。

GUI 检查不仅导入类：显示窗口、导入光谱、改动真实输入控件、触发 ROI 信号、
发送鼠标滚轮事件、点击 Fit、等待工作线程的完成信号、检查结果表和残差曲线。
还检查非法编辑阻止使用旧参数拟合、撤销、峰型切换/删除、项目恢复和导出。
会话测试包括固定参数、FWHM 上下限及边界、Voigt σ/γ 的区分、非空 ROI、
多光谱项目、删除源文件后恢复、损坏项目拒绝、全原始数据和 ROI 曲线导出。

## 模拟演示结果

使用 `examples/create_demo.py` 创建固定种子 42 的 501 点模拟数据。
真实值：峰位 285 eV、Gaussian σ=0.8 eV、面积 100 cps·eV，叠加 Shirley
背景和 0.02 cps 标准差噪声，按降序保存。
实际通过 GUI 导入、添加 Gaussian 峰、后台 Fit、保存项目和导出得到：

| 指标 | GUI 实测 |
|---|---:|
| 峰位 | 284.9991189 eV |
| FWHM | 1.8818693 eV |
| 峰面积 | 99.8276639 cps·eV |
| 峰高 | 49.8344030 cps |
| σ | 0.7991563 eV |
| R² | 0.9999915248 |
| RMSE | 0.03576394 cps |

指标基于全选的 275–295 eV 范围内扣背景后的信号，逐点等权。
背景端点噪声会影响参数与 RMSE，所以本表不要求每个指标恰好等于真值。
独立参数恢复测试也覆盖 Gaussian、Lorentzian 和 Voigt，均通过既定精度断言。

当前实例产物：

- `analysis_output/v02/studio-offscreen.png`：实际 Qt 窗口截图。
- `analysis_output/v02/demo/gaussian.csv/.txt/.xlsx`：模拟实验文件。
- `analysis_output/v02/demo/project.json`：包含数据与结果的可恢复项目。
- `analysis_output/v02/demo/results/`：八个导出文件。

这些演示产物不提交到 Git，避免用生成数据充斥源代码仓库；可用脚本重建。

## Windows 本机与真实数据待验证清单

云端 offscreen 不能替代 Windows 10/11 的真实桌面测试。本次未在 Windows
执行 .cmd 脚本，未验证原生显示、高 DPI、GPU/驱动或用户文件选择器。
本机建议依次检查：

1. 用文档命令或 .cmd 安装/启动，确认 PySide6 平台插件和中文字体正常。
2. 100%、150%、200% 缩放下检查参数表、固定开关、分隔面板与截图导出。
3. 鼠标滚轮、拖动平移、ROI 边界拖动和多个光谱切换。
4. 中文/空格路径、CSV/TXT/XLSX 手动映射与 Excel 工作表切换。
5. 参数预览、上下限、固定/释放、确认与撤销、拟合中界面响应。
6. JSON 另存与重新打开，所有导出文件在 Excel/PDF/SVG 工具中的可读性。
7. 用可信参考结果比较真实谱的端点背景、峰型、残差及定量参数。

科学与 MVP 限制详见 Windows 指南：GUI Voigt 固定 γ/σ；无专业元素模板、
加权/鲁棒拟合、误差传播、能量校准；拟合不可取消，导入/预览/导出未全部
异步化；无自动保存或关闭时未保存提醒。请在关闭窗口前保存项目。
建议完成本机检查后再讨论 EXE 打包与发布。本分支等待用户确认后才能合并。
