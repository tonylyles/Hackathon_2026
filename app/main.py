# main.py — 入口
# 用法：
#   python -m app.main                 # 模式 A：实时风格化全屏
#   python -m app.main --no-style      # 原画预览（验证摄像头）
#   python -m app.main --video in.mp4  # 模式 B：视频批处理风格化 + 合成
#   python -m app.main --serve         # 启动取图服务
import argparse
import time
from pathlib import Path

from app.config import BGM_DIR, DEVICE, OUTPUT_DIR, RECORD_FPS, RECORD_SECONDS


def run_realtime(no_style):
    from app.core.camera import Camera, mirror
    from app.ui.realtime_window import RealtimeWindow
    cam = Camera().start()
    if no_style:
        win = RealtimeWindow(cam, stylizer=lambda f: mirror(mirror(f)))
        win.run()
        return
    from app.core.stylizer_anime import AnimeStylizer
    st = AnimeStylizer(device=DEVICE)
    print("stylizer ready, warming up...")
    st(mirror(cam.read()))
    RealtimeWindow(cam, st).run()


def run_video(video_path):
    from app.core.stylizer_anime import AnimeStylizer
    from app.core.video_batch import extract_frames, stylize_frames, cleanup
    from app.core.compose import frames_to_video

    tmp = Path("tmp") / f"job_{int(time.time())}"
    frames_dir, fps = tmp / "in", tmp / "out"
    print("extracting frames...")
    frames, fps = extract_frames(video_path, frames_dir)
    print(f"{len(frames)} frames @ {fps:.1f}fps, stylizing...")
    st = AnimeStylizer(device=DEVICE)
    styled = stylize_frames(frames, st, frames_dir, progress=lambda done, total: print(f"\r{done}/{total}", end=""))
    print()
    bgms = list(BGM_DIR.glob("*.mp3")) + list(BGM_DIR.glob("*.m4a"))
    out = OUTPUT_DIR / f"video_{int(time.time())}.mp4"
    frames_to_video(frames_dir, out, fps=round(fps), bgm_path=bgms[0] if bgms else None)
    cleanup(tmp)
    print("saved:", out)


def run_serve(port=8000):
    import uvicorn
    from app.server.api import app
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-style", action="store_true")
    ap.add_argument("--video", help="输入视频路径（模式 B）")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    if args.serve:
        run_serve(args.port)
    elif args.video:
        run_video(args.video)
    else:
        run_realtime(args.no_style)
