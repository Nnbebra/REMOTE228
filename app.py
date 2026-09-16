import os
import sys
import io
import json
import time
import socket
import argparse
import asyncio
import ctypes
import subprocess
from pathlib import Path

import tornado.web
import tornado.websocket
import tornado.ioloop
from PIL import Image
import mss
import pyautogui
import psutil

# Ensure PyAutoGUI doesn't crash on screen edges
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.01

# Determine base path (support PyInstaller bundle)
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

WEB_DIR = BASE_DIR / "web"
DEFAULT_PIN = "1234"
DEFAULT_PORT = 8080

def get_local_ip():
    """Retrieve active local network IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

class MainHandler(tornado.web.RequestHandler):
    def get(self):
        index_file = WEB_DIR / "index.html"
        if index_file.exists():
            with open(index_file, "r", encoding="utf-8") as f:
                self.write(f.read())
        else:
            self.write("<h1>StudyRemote Web UI not found</h1>")

class DownloadHandler(tornado.web.RequestHandler):
    def get(self):
        pin = self.get_argument("pin", "")
        if pin != self.application.settings.get("pin"):
            self.set_status(403)
            self.write("Forbidden: Invalid PIN")
            return
        
        file_path = self.get_argument("path", "")
        p = Path(file_path)
        if p.is_file():
            self.set_header('Content-Type', 'application/octet-stream')
            self.set_header('Content-Disposition', f'attachment; filename="{p.name}"')
            with open(p, 'rb') as f:
                self.write(f.read())
        else:
            self.set_status(404)
            self.write("File not found")

class RemoteWebSocketHandler(tornado.websocket.WebSocketHandler):
    clients = set()

    def initialize(self, sct, mon):
        self.sct = sct
        self.mon = mon
        self.streaming = False
        self.stream_task = None
        self.quality_preset = "normal"
        self.scale = 0.55
        self.jpeg_quality = 65
        self.interval = 0.045  # ~22 FPS

    def check_origin(self, origin):
        return True

    def open(self):
        client_pin = self.get_argument("pin", "")
        expected_pin = self.application.settings.get("pin")

        if client_pin != expected_pin:
            self.close(code=4001, reason="Invalid PIN")
            return

        RemoteWebSocketHandler.clients.add(self)
        print(f"[+] Новое подключение: {self.request.remote_ip}")

        # Send initial screen size
        width = self.mon["width"]
        height = self.mon["height"]
        self.write_message(json.dumps({
            "type": "init",
            "width": width,
            "height": height
        }))

        # Start background screen streaming
        self.streaming = True
        self.stream_task = asyncio.create_task(self.stream_screen())

    def on_close(self):
        RemoteWebSocketHandler.clients.discard(self)
        self.streaming = False
        if self.stream_task:
            self.stream_task.cancel()
        print(f"[-] Клиент отключился: {self.request.remote_ip}")

    async def stream_screen(self):
        """Asynchronous screen capture loop"""
        loop = asyncio.get_event_loop()
        while self.streaming:
            t_start = time.time()
            try:
                # Capture and compress frame in executor thread to prevent blocking event loop
                frame_bytes = await loop.run_in_executor(None, self.capture_frame)
                if frame_bytes and self.ws_connection:
                    await self.write_message(frame_bytes, binary=True)
            except Exception as e:
                pass

            elapsed = time.time() - t_start
            sleep_time = max(0.01, self.interval - elapsed)
            await asyncio.sleep(sleep_time)

    def capture_frame(self):
        try:
            raw = self.sct.grab(self.mon)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            
            if self.scale != 1.0:
                new_w = int(raw.width * self.scale)
                new_h = int(raw.height * self.scale)
                img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=self.jpeg_quality, optimize=False)
            return buf.getvalue()
        except Exception:
            return None

    def on_message(self, message):
        try:
            data = json.loads(message)
            mtype = data.get("type")

            if mtype == "input":
                self.handle_input(data)
            elif mtype == "config":
                self.handle_config(data)
            elif mtype == "terminal":
                self.handle_terminal(data)
            elif mtype == "list_files":
                self.handle_list_files(data.get("path", ""))
            elif mtype == "navigate_files":
                self.handle_navigate_files(data)
            elif mtype == "get_stats":
                self.handle_get_stats()
            elif mtype == "power":
                self.handle_power(data.get("action"))
        except Exception as e:
            print(f"[!] Ошибка обработки сообщения: {e}")

    def handle_config(self, data):
        preset = data.get("quality", "normal")
        self.quality_preset = preset
        if preset == "eco":
            self.scale = 0.4
            self.jpeg_quality = 45
            self.interval = 0.08  # ~12 FPS
        elif preset == "high":
            self.scale = 0.75
            self.jpeg_quality = 80
            self.interval = 0.033  # ~30 FPS
        else:  # normal
            self.scale = 0.55
            self.jpeg_quality = 65
            self.interval = 0.045  # ~22 FPS

    def handle_input(self, data):
        action = data.get("action")
        if action == "mousemove":
            x, y = data.get("x", 0), data.get("y", 0)
            pyautogui.moveTo(x, y)
        elif action == "mousedown":
            x, y = data.get("x", 0), data.get("y", 0)
            button = data.get("button", "left")
            pyautogui.mouseDown(x, y, button=button)
        elif action == "mouseup":
            x, y = data.get("x", 0), data.get("y", 0)
            button = data.get("button", "left")
            pyautogui.mouseUp(x, y, button=button)
        elif action == "click":
            x, y = data.get("x", 0), data.get("y", 0)
            button = data.get("button", "left")
            pyautogui.click(x, y, button=button)
        elif action == "scroll":
            delta = data.get("deltaY", 0)
            clicks = -1 if delta > 0 else 1
            pyautogui.scroll(clicks * 120)
        elif action == "type":
            text = data.get("text", "")
            # Type text using clipboard paste for Unicode/Cyrillic support
            try:
                import pyperclip
                pyperclip.copy(text)
                pyautogui.hotkey('ctrl', 'v')
            except Exception:
                pyautogui.write(text)
        elif action == "key":
            key = data.get("key", "").lower()
            key_map = {
                "enter": "enter", "backspace": "backspace", "escape": "esc",
                "tab": "tab", "up": "up", "down": "down", "left": "left", "right": "right"
            }
            mapped = key_map.get(key, key)
            pyautogui.press(mapped)
        elif action == "shortcut":
            combo = data.get("combo", "").lower()
            parts = [p.strip() for p in combo.split("+")]
            if parts == ["win", "l"]:
                ctypes.windll.user32.LockWorkStation()
            else:
                pyautogui.hotkey(*parts)

    def handle_terminal(self, data):
        command = data.get("command", "").strip()
        if not command:
            return
        
        asyncio.create_task(self.run_command_async(command))

    async def run_command_async(self, command):
        loop = asyncio.get_event_loop()
        def _exec():
            try:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="cp866",
                    errors="replace"
                )
                out, _ = proc.communicate(timeout=20)
                return out or "[Команда завершена без вывода]"
            except subprocess.TimeoutExpired:
                return "[Таймаут выполнения команды (20с)]"
            except Exception as e:
                return f"[Ошибка выполнения]: {e}"

        result = await loop.run_in_executor(None, _exec)
        self.write_message(json.dumps({
            "type": "term_output",
            "data": f"{result}\n"
        }))

    def handle_list_files(self, dir_path):
        if not dir_path or not os.path.exists(dir_path):
            dir_path = str(Path.home() / "Desktop")

        items = []
        try:
            for entry in os.scandir(dir_path):
                is_dir = entry.is_dir()
                size_str = ""
                if not is_dir:
                    try:
                        sz = entry.stat().st_size
                        if sz > 1024 * 1024:
                            size_str = f"{sz / (1024*1024):.1f} MB"
                        elif sz > 1024:
                            size_str = f"{sz / 1024:.1f} KB"
                        else:
                            size_str = f"{sz} B"
                    except Exception:
                        size_str = ""
                items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "is_dir": is_dir,
                    "size": size_str
                })
            items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        except Exception as e:
            items.append({"name": f"[Ошибка доступа]: {e}", "path": dir_path, "is_dir": False, "size": ""})

        self.write_message(json.dumps({
            "type": "files",
            "path": dir_path,
            "items": items
        }))

    def handle_navigate_files(self, data):
        rel = data.get("rel")
        current = data.get("current", "")
        if rel == "..":
            new_path = str(Path(current).parent)
        else:
            new_path = current
        self.handle_list_files(new_path)

    def handle_get_stats(self):
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent
        try:
            disk = psutil.disk_usage('C:\\').percent
        except Exception:
            disk = 0

        self.write_message(json.dumps({
            "type": "stats",
            "cpu": cpu,
            "ram": ram,
            "disk": disk
        }))

    def handle_power(self, action):
        if action == "sleep":
            subprocess.run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
        elif action == "mute":
            pyautogui.press("volumemute")


def make_app(pin):
    sct = mss.mss()
    mon = sct.monitors[1]  # primary monitor

    handlers = [
        (r"/", MainHandler),
        (r"/api/download", DownloadHandler),
        (r"/ws", RemoteWebSocketHandler, {"sct": sct, "mon": mon}),
    ]

    return tornado.web.Application(
        handlers,
        pin=pin,
        template_path=WEB_DIR,
        static_path=WEB_DIR,
        websocket_ping_interval=10,
        websocket_ping_timeout=30
    )


def start_tunnel(port):
    """Optional Cloudflare Quick Tunnel launch"""
    cloudflared_path = BASE_DIR / "cloudflared.exe"
    if not cloudflared_path.exists():
        cloudflared_path = Path(sys.executable).parent / "cloudflared.exe"

    if cloudflared_path.exists():
        print("[*] Запуск Cloudflare Quick Tunnel...")
        try:
            cmd = f'"{cloudflared_path}" tunnel --url http://127.0.0.1:{port}'
            p = subprocess.Popen(cmd, shell=True, stderr=subprocess.PIPE, text=True, bufsize=1)
            for line in p.stderr:
                if "trycloudflare.com" in line:
                    for token in line.split():
                        if "https://" in token and "trycloudflare.com" in token:
                            print(f"\n=======================================================")
                            print(f" 🌐 ПУБЛИЧНАЯ ССЫЛКА ДЛЯ ДОСТУПА С ПАР:")
                            print(f" {token}")
                            print(f"=======================================================\n")
                            return
        except Exception as e:
            print(f"[!] Не удалось запустить туннель: {e}")


def main():
    parser = argparse.ArgumentParser(description="StudyRemote — Web Remote Desktop Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on (default: 8080)")
    parser.add_argument("--pin", type=str, default=DEFAULT_PIN, help="Security PIN code (default: 1234)")
    parser.add_argument("--tunnel", action="store_true", help="Launch Cloudflare Quick Tunnel for public URL")
    args = parser.parse_args()

    local_ip = get_local_ip()

    print("=" * 60)
    print("   ⚡ StudyRemote — Веб-сервер удалённого управления ПК")
    print("=" * 60)
    print(f"[*] Локальный адрес:  http://localhost:{args.port}")
    print(f"[*] Адрес в сети:      http://{local_ip}:{args.port}")
    print(f"[*] Защитный PIN-код:  {args.pin}")
    print("=" * 60)
    print("[*] Подключайтесь через браузер смартфона, планшета или ПК.")

    if args.tunnel:
        start_tunnel(args.port)

    app = make_app(args.pin)
    app.listen(args.port)

    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        print("\n[*] Остановка сервера...")


if __name__ == "__main__":
    main()
