# 汇报模板（最终回复用中文，按下面的顺序）

**结果**：一句话说做了什么、效果如何（基于你看过的 compare.jpg 和 focus.jpg，不是复述 JSON）。

**产物**（绝对路径，一行一个）：
- 处理后：`<out>/processed.tif`（16-bit sRGB）、`<out>/processed.jpg`
- 对比图：`<out>/compare.jpg`、1:1 焦点区 `<out>/focus.jpg`（重跑后上一轮在 `*.prev.*`）
- 导出：`<out>/export/print_<paper>_<finish>.jpg`（尺寸, 300 ppi）、`web.jpg`（尺寸, 无 EXIF）、`dating_1x1.jpg` / `dating_4x5.jpg`（尺寸, 无 EXIF）
- 风格文件 / 分析：`<out>/style.json`、`<out>/analysis.json`、`<out>/report.json`；`<out>` 默认是 `~/.dot/photo/output/<stem>-<hash>/`，`<out>/source.json` 记录原图路径；用 `--name` 保存的风格在 `~/.dot/photo/styles/<name>.json`

**参数**（表格，取自 `summary.params_used`）：动作、类型判定及置信度、风格名与强度 / 模式、磨皮强度 / 去雾等关键参数、调参轮次（每轮改了哪些选项、为什么）。来自用户 `config.json` 的默认值（`config_applied`）单独标注为"你的默认"，不算我的判断。

**判断来源**：
- 脚本判定：类型、人脸数、肤色覆盖率、黑白点、指标（texture_retained、halo_ratio…）
- 我的判断：看图后的结论、调过的参数及原因（最多两轮）

**需要你确认**（来自 `needs_review`，一条一行：现象 → 我做了什么 → 建议）；没有则写"无"。

**下一步可选**：一到两条（如调强度、换纸型、换风格），不要展开。

---

# 批量（文件夹）汇报模板

**结果**：一句话说处理了几张、几张成功 / 失败 / 跳过，整体效果如何（基于你看过的 `contact.jpg`，以及点开过的单张 compare / focus）。

**总览图**：`<run dir>/contact.jpg`（多页时逐个列出 `contact-2.jpg` …）；汇总：`<run dir>/batch.json`、`<run dir>/log.txt`；`<run dir>` 是 `out_dir`（默认 `~/.dot/photo/runs/<时间>-<文件夹>/`），每张照片的产物在 `output_root` 下的 `<stem>-<hash>/`。

**逐张**（表格，一行一张，取自 `summary.photos`）：

| 文件（相对路径） | 类型 / 置信度 | 风格 / 关键参数 | needs_review | 产物目录 |
|---|---|---|---|---|

**失败**（有则一行一个：文件 → `error.code` → message → 建议；没有写"无"）。

**需要你确认**（按 `needs_review_counts` 的 code 分组：现象 → 涉及哪些照片 → 我看图后做了什么 → 建议；`TYPE_UNCERTAIN` 列出照片并给出 `--type` 单张重跑的命令）。

**下一步可选**：一到两条（如对某几张单独重跑、`--skip-existing` 续跑、换风格），不要展开。
