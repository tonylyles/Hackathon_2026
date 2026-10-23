# api.py — 作品分享服务：局域网二维码取图/取视频
# 启动：uvicorn app.server.api:app --host 0.0.0.0 --port 8000
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.config import OUTPUT_DIR

app = FastAPI(title="AI PhotoBooth")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def public_media(name: str):
    if not name or name in (".", "..") or "/" in name or "\\" in name or Path(name).name != name:
        return None
    if Path(name).suffix.lower() not in (".png", ".jpg", ".jpeg", ".mp4"):
        return None
    path = (OUTPUT_DIR / name).resolve()
    if path.parent != OUTPUT_DIR.resolve() or not path.is_file():
        return None
    return path


@app.get("/files/{name:path}")
def public_file(name: str):
    path = public_media(name)
    if path is None:
        raise HTTPException(404)
    return FileResponse(path, filename=path.name)



@app.get("/api/items")
def items():
    files = sorted(OUTPUT_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {"name": f.name, "url": f"/files/{f.name}", "type": "video" if f.suffix.lower() == ".mp4" else "image",
         "time": time.strftime("%H:%M:%S", time.localtime(f.stat().st_mtime))}
        for f in files if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".mp4")
    ]


@app.get("/api/download/{name}")
def download(name: str):
    p = public_media(name)
    if p is None:
        raise HTTPException(404)
    return FileResponse(p, filename=p.name)
