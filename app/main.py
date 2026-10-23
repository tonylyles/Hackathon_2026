# main.py — 入口
# 用法：
#   python -m app.main                 # 模式 A：实时风格化全屏
#   python -m app.main --no-style      # 原画预览（验证摄像头）
#   python -m app.main --video in.mp4  # 模式 B：视频批处理风格化 + 合成
#   python -m app.main --serve         # 启动取图服务
import argparse
import time
from pathlib import Path

from app.config import (BGM_DIR, CAMERA_BACKEND, CAMERA_H, CAMERA_INDEX, CAMERA_W,
                        DEVICE, OUTPUT_DIR, RECORD_SECONDS, RECORD_FPS,
                        VTS_API_URL, VTS_PLUGIN_NAME, VTS_PLUGIN_DEVELOPER,
                        VTS_TIMEOUT_SECONDS)


def get_stylizer(engine):
    if engine == "mock":
        from app.core.stylizer_mock import MockStylizer
        return MockStylizer()
    from app.core.stylizer_anime import AnimeStylizer
    return AnimeStylizer(device=DEVICE)


def open_camera():
    from app.core.camera import Camera
    print(f"camera index={CAMERA_INDEX} backend={CAMERA_BACKEND} size={CAMERA_W}x{CAMERA_H}")
    return Camera(index=CAMERA_INDEX, width=CAMERA_W, height=CAMERA_H,
                  backend=CAMERA_BACKEND).start()


def wait_for_frame(cam):
    deadline = time.monotonic() + 10
    frame = cam.read()
    while frame is None and time.monotonic() < deadline:
        time.sleep(0.01)
        frame = cam.read()
    if frame is None:
        raise RuntimeError(f"摄像头 {CAMERA_INDEX} ({CAMERA_BACKEND}) 在 10 秒内没有返回画面")
    return frame


def run_realtime(no_style, engine="anime"):
    from app.core.camera import mirror
    from app.ui.realtime_window import RealtimeWindow
    cam = open_camera()
    try:
        frame = wait_for_frame(cam)
        if no_style:
            RealtimeWindow(cam, stylizer=lambda f: f).run()
            return
        st = get_stylizer(engine)
        print("stylizer ready, warming up...")
        st(mirror(frame))
        RealtimeWindow(cam, st).run()
    finally:
        cam.stop()


def run_booth(no_style=False, engine="anime", port=8000):
    from app.core.camera import mirror
    from app.ui.booth_window import BoothWindow
    from app.server.share import ShareServer

    cam = open_camera()
    try:
        frame = wait_for_frame(cam)
        st = get_stylizer(engine)
        if not no_style:
            st(mirror(frame))
        with ShareServer(port=port) as server:
            BoothWindow(cam, st, port=port, show_styled=not no_style,
                        record_seconds=RECORD_SECONDS, record_fps=RECORD_FPS,
                        share_ready=server.ready.is_set).run()
    finally:
        cam.stop()


def run_video(video_path, engine="anime"):
    from app.core.video_batch import extract_frames, stylize_frames, cleanup
    from app.core.compose import frames_to_video

    tmp = Path("tmp") / f"job_{int(time.time())}"
    frames_dir, styled_dir = tmp / "in", tmp / "out"
    print("extracting frames...")
    frames, fps = extract_frames(video_path, frames_dir)
    print(f"{len(frames)} frames @ {fps:.1f}fps, stylizing...")
    st = get_stylizer(engine)
    styled = stylize_frames(frames, st, styled_dir, progress=lambda done, total: print(f"\r{done}/{total}", end=""))
    print()
    bgms = list(BGM_DIR.glob("*.mp3")) + list(BGM_DIR.glob("*.m4a"))
    out = OUTPUT_DIR / f"video_{int(time.time())}.mp4"
    frames_to_video(styled_dir, out, fps=fps, bgm_path=bgms[0] if bgms else None)
    cleanup(tmp)
    print("saved:", out)


def run_avatar_booth():
    from app.core.vts_client import VTSClient
    from app.core.vts_controller import VTSController
    from app.ui.avatar_booth_window import AvatarBoothWindow

    client = VTSClient(url=VTS_API_URL, plugin_name=VTS_PLUGIN_NAME,
                       plugin_developer=VTS_PLUGIN_DEVELOPER,
                       timeout=VTS_TIMEOUT_SECONDS)
    AvatarBoothWindow(VTSController(client)).run()


def run_serve(port=8000):
    import uvicorn
    from app.server.api import app
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-style", action="store_true")
    ap.add_argument("--engine", choices=["anime", "mock"], default="anime",
                    help="anime=AnimeGANv2（需装好环境）mock=纯流程验证（零依赖）")
    ap.add_argument("--video", help="输入视频路径（模式 B）")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--booth", action="store_true", help="拍照/4秒录像展台模式")
    ap.add_argument("--avatar-booth", action="store_true", help="VTube Studio 奶蛙控制台")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    if args.avatar_booth:
        run_avatar_booth()
    elif args.serve:
        run_serve(args.port)
    elif args.booth:
        run_booth(args.no_style, args.engine, args.port)
    elif args.video:
        run_video(args.video, args.engine)
    else:
        run_realtime(args.no_style, args.engine)
