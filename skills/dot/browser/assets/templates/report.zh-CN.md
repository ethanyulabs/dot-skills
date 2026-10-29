# 报告模板（中文）

**结果**：一句话说清做到了什么，或者卡在哪。

**位置**：浏览器 `<Arc / Chrome / Edge>`，空间 `<title>`（Arc）/ dot 专用窗口（Chrome / Edge），标签页「<title>」`<url>`，会话 `<name>`（已关闭 / 按要求保留）。

**操作记录**：

| 步骤 | 动作 | 目标 | 之后 |
|---|---|---|---|
| 1 | open | `<url>` | 标题「…」 |
| 2 | click | e12 button "登录" | 跳转到 `<url>` |
| 3 | fill + Enter | e7 textbox "搜索" ← "…" | 列表出现 N 行 |

**产物**（绝对路径）：截图 `…/output/<session>/<stamp>-screenshot.png`（已用 Read 打开，看到 …）；提取文本 `…`。

**判断来源**：哪些结论来自快照 / 提取（脚本给的），哪些来自我看截图得出的。

**未能执行**（没有就删掉这一段）：例如「Arc 未开调试端口，快照 / 点击 / 截图不可用；标题和地址来自 Arc 的标签信息（open / tabs）」，附重启命令；或「该站点需要在 dot 的 Chrome 专用窗口里登录一次」。

**需要你确认**：未执行的敏感操作（支付 / 发送 / 删除 / 授权）、需要你登录的页面、弹窗、`REF_STALE` 重试了几次、是否要把 `<space>` 设为默认空间（`dbrowser config set arc.space=…`）、把 `<browser>` 设为默认浏览器（`dbrowser config set browser=…`）；Chrome / Edge 任务结束后是否退出 dot 的实例（`dbrowser quit --browser …`）。

**下一步可选**：…
