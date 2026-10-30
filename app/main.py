# main.py — 入口
# 用法：
#   python -m app.main                 # 模式 A：实时风格化全屏
#   python -m app.main --booth         # 真人摄像头：动漫主画面 + 原画小窗
#   python -m app.main --video in.mp4  # 模式 B：视频批处理风格化 + 合成
#   python -m app.main --serve         # 启动取图服务
import argparse
import time
from pathlib import Path

from app.config import (BGM_DIR, CAMERA_BACKEND, CAMERA_H, CAMERA_INDEX, CAMERA_W,
                        DEVICE, OUTPUT_DIR, RECORD_SECONDS, RECORD_FPS,
                        VTS_API_URL, VTS_PLUGIN_NAME, VTS_PLUGIN_DEVELOPER,
                        VTS_TIMEOUT_SECONDS, VTS_CAMERA_INDEX, VTS_CAMERA_BACKEND,
                        VTS_CAMERA_W, VTS_CAMERA_H, VTS_PREVIEW_ENABLED, VTS_AUTO_LAUNCH)


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
    from app.core.camera import frame_is_black

    deadline = time.monotonic() + 10
    frame = None
    saw_black = False
    while time.monotonic() < deadline:
        frame = cam.read(only_new=True)
        if frame is not None:
            if not frame_is_black(frame):
                return frame
            saw_black = True
        time.sleep(0.05)
    if saw_black or getattr(cam, "black_frame_seen", False):
        reason = "返回了持续黑帧"
    else:
        reason = "没有返回画面"
    raise RuntimeError(
        f"摄像头 {CAMERA_INDEX} ({CAMERA_BACKEND}) 在 10 秒内{reason}。"
        "请检查镜头是否遮挡、Camo Studio 是否有画面，或关闭占用摄像头的程序；"
        "可运行 scripts/test_cameras.py 查看各设备截图并调整 app/config.py。"
    )


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


def run_booth(no_style=False, engine="anime", port=8000, vts_preview=False):
    from app.ui.booth_window import BoothWindow
    from app.server.share import ShareServer

    cam = None if vts_preview else open_camera()
    avatar_feed = None
    controller = None
    vts_api_error = None
    try:
        frame = None if vts_preview else wait_for_frame(cam)
        if vts_preview:
            st = lambda image: image
            def camera_stylizer():
                return (lambda image: image) if no_style else get_stylizer(engine)
        elif no_style:
            st = lambda image: image
        else:
            st = get_stylizer(engine)
            from app.core.camera import mirror
            st(mirror(frame))
        if vts_preview:
            from app.core.vts_client import VTSClient
            from app.core.vts_controller import VTSController
            from app.core.vts_video import VTSVideoFeed
            from app.core.vts_launcher import VTSLauncher

            client = VTSClient(url=VTS_API_URL, plugin_name=VTS_PLUGIN_NAME,
                               plugin_developer=VTS_PLUGIN_DEVELOPER,
                               timeout=VTS_TIMEOUT_SECONDS)
            controller = VTSController(client)
            launcher = VTSLauncher(enabled=VTS_AUTO_LAUNCH)
            avatar_feed = VTSVideoFeed(VTS_CAMERA_INDEX, VTS_CAMERA_BACKEND,
                                       width=VTS_CAMERA_W, height=VTS_CAMERA_H,
                                       named_fallback=True).start()
        with ShareServer(port=port) as server:
            BoothWindow(cam, st, port=port, show_styled=not no_style,
                        record_seconds=RECORD_SECONDS, record_fps=RECORD_FPS,
                        share_ready=server.ready.is_set,
                        avatar_feed=avatar_feed, vts_controller=controller,
                        vts_capture=vts_preview, vts_api_error=vts_api_error,
                        camera_opener=open_camera if vts_preview else None,
                        camera_stylizer=camera_stylizer if vts_preview else None,
                        vts_launcher=launcher if vts_preview else None).run()
    finally:
        if avatar_feed:
            avatar_feed.close()
        if controller:
            controller.close()
        if cam is not None:
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
    ap.add_argument("--vts-preview", action="store_true", help="以 VTube Studio 虚拟摄像头作为展台拍摄源（不使用本地动漫风格化）")
    ap.add_argument("--avatar-booth", action="store_true", help="VTube Studio 奶蛙控制台")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    if args.avatar_booth:
        run_avatar_booth()
    elif args.serve:
        run_serve(args.port)
    elif args.booth:
        run_booth(args.no_style, args.engine, args.port,
                  vts_preview=args.vts_preview or VTS_PREVIEW_ENABLED)
    elif args.video:
        run_video(args.video, args.engine)
    else:
        run_realtime(args.no_style, args.engine)
