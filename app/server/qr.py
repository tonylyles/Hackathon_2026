# qr.py — 生成取图二维码（内容为局域网链接）
import socket

import qrcode


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def item_url(ip, port, name):
    return f"http://{ip}:{port}/api/download/{name}"


def make_qr(data: str, path: str):
    img = qrcode.make(data)
    img.save(path)
    return path
