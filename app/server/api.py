# api.py — 作品分享服务：局域网二维码取图/取视频
# 启动：uvicorn app.server.api:app --host 0.0.0.0 --port 8000
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import OUTPUT_DIR

app = FastAPI(title="AI PhotoBooth")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(OUTPUT_DIR)), name="files")


@app.get("/api/items")
def items():
    files = sorted(OUTPUT_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {"name": f.name, "url": f"/files/{f.name}", "type": "video" if f.suffix == ".mp4" else "image",
         "time": time.strftime("%H:%M:%S", time.localtime(f.stat().st_mtime))}
        for f in files if f.suffix in (".png", ".jpg", ".mp4")
    ]


@app.get("/api/download/{name}")
def download(name: str):
    p = OUTPUT_DIR / name
    if not p.exists() or ".." in name:
        raise HTTPException(404)
    return FileResponse(p, filename=name)
