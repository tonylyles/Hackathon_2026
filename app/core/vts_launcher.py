"""Start the Steam VTube Studio installation at most once per booth session."""
import csv
import os
import subprocess


def vts_process_running():
    """Return None if process detection failed; never launch on uncertainty."""
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq VTube Studio.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        rows = list(csv.reader(result.stdout.splitlines()))
        return any(row and row[0].strip().lower() == "vtube studio.exe" for row in rows)
    except (OSError, subprocess.SubprocessError, UnicodeError, csv.Error):
        return None


class VTSLauncher:
    """Coordinate Steam startup without touching a running VTS process."""

    def __init__(self, process_running=vts_process_running, start=None, enabled=True,
                 steam_app_id=1325860):
        self.process_running = process_running
        self.start = start if start is not None else (os.startfile if os.name == "nt" else None)
        self.enabled = enabled
        self.steam_app_id = steam_app_id
        self.launch_attempted = False

    def ensure_started(self):
        running = self.process_running()
        if running is True:
            return "VTube Studio 已运行，正在连接 API…"
        if self.launch_attempted:
            return "VTube Studio 启动已尝试，请检查 Steam 和 VTS，再点重试连接"
        if not self.enabled:
            return "VTube Studio 未运行，请手动打开后重试"
        if running is None:
            return "无法确认 VTube Studio 是否运行，请手动打开，避免重复启动"
        if self.start is None:
            return "此系统不支持自动启动 VTube Studio，请手动打开后重试"
        self.launch_attempted = True
        try:
            self.start(f"steam://rungameid/{self.steam_app_id}")
        except OSError as exc:
            return f"无法通过 Steam 启动 VTube Studio：{exc}"
        return "已向 Steam 请求启动 VTube Studio，正在等待 API…"
