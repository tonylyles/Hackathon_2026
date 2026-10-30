# 无设备预览性能诊断

在工程根目录运行：

```powershell
.venv\Scripts\python.exe scripts\profile_preview.py --samples 30 --warmup 3 --json tmp\preview-report.json
```

可用 `--width` / `--height` 指定绿幕输入尺寸；`--cprofile tmp\preview.prof` 生成可由 pstats 读取的阶段调用统计。不指定路径只向控制台输出 JSON，不写媒体文件，不打开摄像头、VTube Studio API 或图形窗口。使用 1280×720 合成绿幕、中心色块、递增 sequence；每次完整路径样本都处理新帧。`same_sequence_early_return` 独立计时，不能算成新帧吞吐。

所有 `mean_ms`、`p50_ms`、`p95_ms`、`p99_ms` 是单阶段的内部处理时间；`internal_iterations_per_second` 是合成数据在本机的迭代能力。`full_internal_path` 包含更新合成帧及 UI 画布，但不包含虚拟摄像头采集、GUI `imshow`、显示器实际刷新或观众动作到屏幕时间，因此**不是端到端延迟或实际帧率**。`background_cold` 为新 Catalog 实例、非清空操作系统文件缓存；`background_warm` 重用同一实例。小样本波动很大，请在同环境、相同参数、无额外负载时多次对比，并查看 P95/P99 与均值。

已保留小样本本机基线于忽略跟踪的 `tmp/preview-before.json`，缓存后结果于 `tmp/preview-after.json`。这两份报告各只有 5 次采样，可用于快速烟测，不适合作为正式性能承诺。实际端到端延迟仍需真实 VTS 输入和显示侧外部观测。
