# 汇报模板（最终回复用中文，按下面的顺序）

**结果**：一句话说做了什么、效果如何（基于你看过的 compare.jpg 和 focus.jpg，不是复述 JSON）。

**产物**（绝对路径，一行一个）：
- 处理后：`<out>/processed.tif`（16-bit sRGB）、`<out>/processed.jpg`
- 对比图：`<out>/compare.jpg`、1:1 焦点区 `<out>/focus.jpg`（重跑后上一轮在 `*.prev.*`）
- 导出：`<out>/export/print_<paper>_<finish>.jpg`（尺寸, 300 ppi）、`web.jpg`（尺寸, 无 EXIF）、`dating_1x1.jpg` / `dating_4x5.jpg`（尺寸, 无 EXIF）
- 风格文件 / 分析：`<out>/style.json`、`<out>/analysis.json`、`<out>/report.json`

**参数**（表格，取自 `summary.params_used`）：动作、类型判定及置信度、风格名与强度 / 模式、磨皮强度 / 去雾等关键参数、调参轮次（每轮改了哪些选项、为什么）。

**判断来源**：
- 脚本判定：类型、人脸数、肤色覆盖率、黑白点、指标（texture_retained、halo_ratio…）
- 我的判断：看图后的结论、调过的参数及原因（最多两轮）

**需要你确认**（来自 `needs_review`，一条一行：现象 → 我做了什么 → 建议）；没有则写"无"。

**下一步可选**：一到两条（如调强度、换纸型、换风格），不要展开。
