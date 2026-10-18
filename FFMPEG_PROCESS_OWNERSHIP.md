# FFmpeg executable identification and process ownership
# FFmpeg 可执行文件识别与进程归属

## Problem / 问题

On Windows, a recorder can coexist with other FFmpeg installations. Invoking `ffmpeg` by command name relies on executable-search behavior, so it may run an unintended copy. Reporting a subprocess PID is useful, but a PID alone is not evidence that the process belongs to a given recorder installation.

在 Windows 上，录制器可能与其他 FFmpeg 安装共存。仅按命令名调用 `ffmpeg` 依赖可执行文件查找机制，可能启动非预期的副本。子进程 PID 有助于监控，但无法单独证明进程属于特定录制器安装。

## Proposed behavior / 建议行为

1. On Windows, resolve `<recorder installation>/ffmpeg/ffmpeg.exe` to an absolute path.
2. If absent at first start, preserve the existing installer: download/extract FFmpeg into the recorder directory and validate the local executable. Do not treat a system-wide FFmpeg as a successful local installation.
3. Use the absolute local path for version checks, recording and conversion. If unavailable or unusable, report failure rather than silently using another FFmpeg.
4. Do not prepend the private FFmpeg folder to `os.environ['PATH']`. Direct executable paths remove that dependency.
5. Process supervisors should independently verify the running executable path before attempting process termination, even when event-reported PIDs match.

1. 在 Windows 上，将 `<录制器安装目录>/ffmpeg/ffmpeg.exe` 解析为绝对路径。
2. 首次启动若缺失，应保留原有下载安装功能，并验证本地文件。系统其他位置的 FFmpeg 不能替代本地安装成功的判定。
3. 使用本地绝对路径执行版本检查、录制及转换；若无法使用，应报告失败，不应静默调用其他 FFmpeg。
4. 不应将私有 FFmpeg 目录加入 `os.environ['PATH']`，因为直接使用路径已足够。
5. 进程管理程序即使取得事件报告的 PID，也应在结束进程前独立核实其可执行文件路径。

## Scope and compatibility / 范围与兼容性

Setting `os.environ['PATH']` changes the environment of the running Python process and usually its children, **not** the global Windows user/system PATH. Avoiding this modification prevents surprising executable selection in children; it does not claim that the original recorder permanently changed system settings.

修改 `os.environ['PATH']` 会影响当前 Python 进程及通常由其启动的子进程，**不会**永久改变 Windows 用户/系统级 PATH。避免这一修改可减少子进程意外选择可执行文件的风险。

Strict local-only behavior changes Windows installations that intentionally use a system-wide FFmpeg. For upstream adoption, maintainers may prefer an optional strict-local mode or another configurable policy. Non-Windows FFmpeg installation behavior is intended to remain unchanged. This is a standalone proposal independent of any particular GUI or add-on.

严格的本地优先策略会改变有意使用系统级 FFmpeg 的 Windows 用户的行为。上游维护者可考虑可选的严格本地模式或其他可配置策略。此提议不打算改变非 Windows 系统的 FFmpeg 安装行为，也不依赖特定 GUI 或附加工具。

## Verification to perform / 待进行的验证

- Bundled FFmpeg already present: verify recording and conversion use its exact path.
- Local FFmpeg absent, system copy present: verify first-run download installs and executes only the local copy.
- Download fails or local executable is invalid: verify no recording uses another copy.
- Multiple recorder installations: verify separate child executable paths.
- Confirm non-Windows behavior is unchanged.

These are **proposed tests**, not yet completed frozen-build test results.

这些是**建议测试**，并非已完成的打包程序测试结果。
