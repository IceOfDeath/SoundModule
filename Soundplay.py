from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
import threading
import time
import winsound
from collections import OrderedDict
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Optional

import pystray
import requests
import soundfile as sf
from flask import Flask, Response, jsonify, request
from PIL import Image, ImageDraw

HOST, PORT = "127.0.0.1", 1488
ROOT = Path("C:/Matcha")
WORKSPACE = ROOT / "workspace"
SOUND_DIR = WORKSPACE / "soundmodule"
CONFIG_PATH = SOUND_DIR / "config.json"
STATUS_PATH = SOUND_DIR / "Status.txt"
CANONICAL_EXE = SOUND_DIR / "Matchasoundmodule.exe"
SUPPORTED_FORMATS = {"wav", "mp3", "ogg"}
SIZE_OPTIONS = (1, 2, 4, 8, 16, 32, 64, 128)
CACHE_OPTIONS = (256, 512, 1024, 2048, 4096)
DEFAULT_CONFIG = {"maximum_audio_size_mb": 16, "maximum_cache_size_mb": 512,
                  "sound_player": True, "auto_startup": False}
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "Assets"
REASONS = json.loads((RESOURCE_DIR / "Reasons.json").read_text(encoding="utf-8"))


class ErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    INVALID_AUDIO_REQUEST = "invalid_audio_request"
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_AUDIO = "unsupported_audio"
    DOWNLOAD_TIMEOUT = "download_timeout"
    DOWNLOAD_HTTP_REJECTED = "download_http_rejected"
    DOWNLOAD_CONNECTION = "download_connection"
    DOWNLOAD_RESPONSE = "download_response"
    INVALID_CONTENT_LENGTH = "invalid_content_length"
    SAVE_AUDIO = "save_audio"
    CONVERT_AUDIO = "convert_audio"
    AUDIO_NOT_FOUND = "audio_not_found"
    PLAY_FAILED = "play_failed"
    DELETE_AUDIO = "delete_audio"

app = Flask(__name__)
last_status_request = 0.0
state_lock = threading.RLock()
audio_cache: OrderedDict[Path, bytes] = OrderedDict()
cache_size = 0
config = DEFAULT_CONFIG.copy()
tray: Optional[pystray.Icon] = None


def fail(code: ErrorCode, **values):
    return jsonify(error=REASONS[code.value]["message"].format(**values)), 400


def http_reason(response: requests.Response) -> str:
    reason = f"HTTP {response.status_code} {response.reason}".strip()
    if response.headers.get("CF-RAY"):
        reason += " (Cloudflare blocked the request)"
    return reason[:200]


def validate_audio_name(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name or len(name) > 120 or any(x in name for x in ("/", "\\", "..", ":")):
        return None
    return name


def initialise_paths() -> bool:
    if not ROOT.is_dir() or not WORKSPACE.is_dir():
        return False
    SOUND_DIR.mkdir(exist_ok=True)
    ensure_status_file()
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            config.update({key: loaded[key] for key in DEFAULT_CONFIG if key in loaded})
        except (OSError, json.JSONDecodeError):
            pass
    save_config()
    apply_autostart()
    return True


def ensure_status_file() -> None:
    try:
        if not STATUS_PATH.exists() or STATUS_PATH.read_text(encoding="utf-8").strip().lower() != "true":
            STATUS_PATH.write_text("true", encoding="utf-8")
    except OSError:
        pass


def monitor_status_file() -> None:
    while True:
        ensure_status_file()
        time.sleep(10)


def save_config() -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def apply_autostart() -> None:
    if not getattr(sys, "frozen", False):
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as key:
            if config["auto_startup"]:
                winreg.SetValueEx(key, "MatchaSoundModule", 0, winreg.REG_SZ, f'"{CANONICAL_EXE}"')
            else:
                try:
                    winreg.DeleteValue(key, "MatchaSoundModule")
                except FileNotFoundError:
                    pass
    except OSError:
        pass


def detect_format(data: bytes) -> Optional[str]:
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"OggS"):
        return "ogg"
    if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


def cache_audio(path: Path) -> bytes:
    global cache_size
    data = path.read_bytes()
    with state_lock:
        old = audio_cache.pop(path, None)
        if old is not None:
            cache_size -= len(old)
        limit = config["maximum_cache_size_mb"] * 1024 * 1024
        while audio_cache and cache_size + len(data) > limit:
            _, removed = audio_cache.popitem(last=False)
            cache_size -= len(removed)
        if len(data) <= limit:
            audio_cache[path] = data
            cache_size += len(data)
    return data


def get_audio_path(name: str) -> Optional[Path]:
    candidate = SOUND_DIR / f"{name}.wav"
    return candidate if candidate.is_file() else None


def convert_to_wav(data: bytes, target: Path) -> None:
    temporary = target.with_suffix(".wav.tmp")
    try:
        with sf.SoundFile(BytesIO(data)) as source:
            with sf.SoundFile(temporary, "w", samplerate=source.samplerate,
                              channels=source.channels, format="WAV", subtype="PCM_16") as output:
                while True:
                    block = source.read(65_536, dtype="float32")
                    if len(block) == 0:
                        break
                    output.write(block)
        temporary.replace(target)
    except (OSError, RuntimeError, ValueError):
        temporary.unlink(missing_ok=True)
        raise


def play(path: Path) -> None:
    cache_audio(path)
    if not config["sound_player"]:
        return
    try:
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except RuntimeError as exc:
        raise RuntimeError("Failed to play AudioFile") from exc


def remove_audio(path: Path) -> None:
    global cache_size
    path.unlink()
    with state_lock:
        cached = audio_cache.pop(path, None)
        if cached is not None:
            cache_size -= len(cached)


@app.get("/Status")
def status():
    global last_status_request
    last_status_request = time.monotonic()
    return Response("Active", mimetype="text/plain")


@app.post("/Download")
def download():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return fail(ErrorCode.INVALID_REQUEST)
    link, name = payload.get("Link"), validate_audio_name(payload.get("AudioName"))
    if not isinstance(link, str) or not name or not link.lower().startswith(("http://", "https://")):
        return fail(ErrorCode.INVALID_AUDIO_REQUEST)
    if get_audio_path(name):
        return Response("Success", mimetype="text/plain")
    try:
        response = requests.get(link, stream=True, timeout=(5, 30))
        response.raise_for_status()
        limit = config["maximum_audio_size_mb"] * 1024 * 1024
        content_length = int(response.headers.get("Content-Length", "0"))
        if content_length > limit:
            return fail(ErrorCode.FILE_TOO_LARGE)
        chunks, total = [], 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                return fail(ErrorCode.FILE_TOO_LARGE)
            chunks.append(chunk)
        data = b"".join(chunks)
    except requests.Timeout:
        return fail(ErrorCode.DOWNLOAD_TIMEOUT)
    except requests.HTTPError as exc:
        reason = http_reason(exc.response) if exc.response is not None else "unknown HTTP error"
        return fail(ErrorCode.DOWNLOAD_HTTP_REJECTED, reason=reason)
    except requests.ConnectionError:
        return fail(ErrorCode.DOWNLOAD_CONNECTION)
    except requests.RequestException:
        return fail(ErrorCode.DOWNLOAD_RESPONSE)
    except ValueError:
        return fail(ErrorCode.INVALID_CONTENT_LENGTH)
    extension = detect_format(data)
    if extension not in SUPPORTED_FORMATS:
        return fail(ErrorCode.UNSUPPORTED_AUDIO)
    target = SOUND_DIR / f"{name}.wav"
    try:
        convert_to_wav(data, target)
    except (OSError, RuntimeError, ValueError):
        return fail(ErrorCode.CONVERT_AUDIO)
    try:
        cache_audio(target)
    except OSError:
        return fail(ErrorCode.SAVE_AUDIO)
    return Response("Success", mimetype="text/plain")


@app.post("/Play")
def play_audio():
    payload = request.get_json(silent=True)
    name = validate_audio_name(payload.get("Audioname")) if isinstance(payload, dict) else None
    path = get_audio_path(name) if name else None
    if not path:
        return fail(ErrorCode.AUDIO_NOT_FOUND)
    try:
        play(path)
    except (OSError, RuntimeError):
        return fail(ErrorCode.PLAY_FAILED)
    return Response("Success", mimetype="text/plain")


@app.post("/Del")
def delete_audio():
    payload = request.get_json(silent=True)
    name = validate_audio_name(payload.get("AudioName")) if isinstance(payload, dict) else None
    path = get_audio_path(name) if name else None
    if not path:
        return fail(ErrorCode.AUDIO_NOT_FOUND)
    try:
        remove_audio(path)
    except OSError:
        return fail(ErrorCode.DELETE_AUDIO)
    return Response("Success", mimetype="text/plain")


def circle_icon(colour: str) -> Image.Image:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 60, 60), fill=colour, outline="#FFFFFF", width=3)
    return image


def connected() -> bool:
    return time.monotonic() - last_status_request <= 5


def status_label(_item=None) -> str:
    return "Connected" if connected() else "Disconnected"


def set_config(key: str, value) -> None:
    config[key] = value
    save_config()
    if key == "auto_startup":
        apply_autostart()


def select_size(value: int):
    return lambda icon, item: set_config("maximum_audio_size_mb", value)


def select_cache(value: int):
    return lambda icon, item: set_config("maximum_cache_size_mb", value)


def toggle(key: str):
    return lambda icon, item: set_config(key, not config[key])


def radio_items(values, key: str, suffix: str):
    def label(value: int) -> str:
        return f"{value // 1024}GB" if suffix == "MB" and value >= 1024 else f"{value}{suffix}"
    return tuple(pystray.MenuItem(label(value), select_size(value) if key == "maximum_audio_size_mb" else select_cache(value),
                                  checked=lambda item, v=value: config[key] == v,
                                  radio=True) for value in values)


def exit_app(icon, item) -> None:
    icon.stop()
    os._exit(0)


def update_tray() -> None:
    while True:
        if tray:
            tray.icon = circle_icon("#32B643" if connected() else "#E53935")
            tray.update_menu()
        time.sleep(1)


def run_server() -> None:
    app.run(host=HOST, port=PORT, threaded=True, use_reloader=False)


def hold_single_instance() -> bool:
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\MatchaSoundModule")
    return not (handle and ctypes.windll.kernel32.GetLastError() == 183)


def launch_workspace_copy() -> None:
    if not getattr(sys, "frozen", False):
        return
    current = Path(sys.executable)
    if current.resolve() == CANONICAL_EXE.resolve():
        return
    if not ROOT.is_dir() or not WORKSPACE.is_dir():
        return
    try:
        SOUND_DIR.mkdir(exist_ok=True)
        shutil.copy2(current, CANONICAL_EXE)
        os.startfile(str(CANONICAL_EXE))
        sys.exit(0)
    except OSError:
        pass


def main() -> None:
    launch_workspace_copy()
    if not hold_single_instance():
        return
    if not initialise_paths():
        ctypes.windll.user32.MessageBoxW(0, "Failed to find Matcha path", "Matcha Sound Module", 0x10)
        return
    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=monitor_status_file, daemon=True).start()
    global tray
    menu = pystray.Menu(
        pystray.MenuItem(status_label, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Maximum audio size", pystray.Menu(*radio_items(SIZE_OPTIONS, "maximum_audio_size_mb", "MB"))),
        pystray.MenuItem("Maximum cache size", pystray.Menu(*radio_items(CACHE_OPTIONS, "maximum_cache_size_mb", "MB"))),
        pystray.MenuItem("Sound Player", toggle("sound_player"), checked=lambda item: config["sound_player"]),
        pystray.MenuItem("AutoStartup", toggle("auto_startup"), checked=lambda item: config["auto_startup"]),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", exit_app),
    )
    tray = pystray.Icon("MatchaSoundModule", circle_icon("#E53935"), "Matcha Sound Module", menu)
    threading.Thread(target=update_tray, daemon=True).start()
    tray.run()


if __name__ == "__main__":
    main()
