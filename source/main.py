import os
import re
import json
import time
import shutil
import signal
import select
import struct
import fcntl
import termios
import tempfile
import threading
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify, Response
from flask_sock import Sock

APP_NAME = "vstermu PRO"
HOST = "127.0.0.1"
PORT = int(os.environ.get("VSTERMU_PORT", "8000"))
HOME = os.path.realpath(os.path.expanduser("~"))
SHARED = "/storage/emulated/0"
DATA_ROOT = os.path.join(SHARED, "vstemu-data")
SCRIPTS_SAVE = os.path.join(DATA_ROOT, "scripts.save")
STYLE_DIR = os.path.join(DATA_ROOT, "Style")
STYLE_FILE = os.path.join(STYLE_DIR, "style.json")
STATE_FILE = os.path.join(SCRIPTS_SAVE, "state.json")
MAX_FILE_SIZE = 8 * 1024 * 1024
MAX_SCAN_ITEMS = 3000

app = Flask(__name__)
sock = Sock(app)

DEFAULT_STYLE = {
    "theme": "dark",
    "fontSize": 14,
    "editorFontSize": 14,
    "terminalFontSize": 14,
    "sidebarWidth": 280,
    "terminalHeight": 280,
    "wordWrap": True,
}

EXTENSIONS = {
    "js": "fa-brands fa-js",
    "mjs": "fa-brands fa-js",
    "cjs": "fa-brands fa-js",
    "ts": "fa-brands fa-js",
    "tsx": "fa-brands fa-react",
    "jsx": "fa-brands fa-react",
    "html": "fa-brands fa-html5",
    "htm": "fa-brands fa-html5",
    "css": "fa-brands fa-css3-alt",
    "scss": "fa-brands fa-sass",
    "py": "fa-brands fa-python",
    "json": "fa-solid fa-brackets-curly",
    "xml": "fa-solid fa-code",
    "svg": "fa-solid fa-bezier-curve",
    "md": "fa-brands fa-markdown",
    "txt": "fa-solid fa-file-lines",
    "sh": "fa-solid fa-terminal",
    "bash": "fa-solid fa-terminal",
    "zsh": "fa-solid fa-terminal",
    "fish": "fa-solid fa-fish",
    "php": "fa-brands fa-php",
    "java": "fa-brands fa-java",
    "c": "fa-solid fa-c",
    "cpp": "fa-solid fa-code",
    "h": "fa-solid fa-code",
    "hpp": "fa-solid fa-code",
    "rs": "fa-brands fa-rust",
    "go": "fa-brands fa-golang",
    "sql": "fa-solid fa-database",
    "yaml": "fa-solid fa-file-code",
    "yml": "fa-solid fa-file-code",
    "toml": "fa-solid fa-file-code",
    "ini": "fa-solid fa-sliders",
    "env": "fa-solid fa-gears",
    "lock": "fa-solid fa-lock",
    "zip": "fa-solid fa-file-zipper",
    "tar": "fa-solid fa-box-archive",
    "gz": "fa-solid fa-box-archive",
    "png": "fa-solid fa-image",
    "jpg": "fa-solid fa-image",
    "jpeg": "fa-solid fa-image",
    "webp": "fa-solid fa-image",
    "gif": "fa-solid fa-image",
    "mp3": "fa-solid fa-music",
    "wav": "fa-solid fa-music",
    "mp4": "fa-solid fa-film",
    "mkv": "fa-solid fa-film",
    "pdf": "fa-solid fa-file-pdf",
}


def ensure_data_files():
    os.makedirs(SCRIPTS_SAVE, exist_ok=True)
    os.makedirs(STYLE_DIR, exist_ok=True)

    if not os.path.exists(STYLE_FILE):
        atomic_json_write(STYLE_FILE, DEFAULT_STYLE)

    if not os.path.exists(STATE_FILE):
        atomic_json_write(
            STATE_FILE,
            {
                "openFiles": [],
                "lastFile": None
            }
        )


def atomic_json_write(path, value):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)

    fd, temp = tempfile.mkstemp(
        prefix=".vstemu-",
        dir=directory,
        text=True
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                value,
                handle,
                ensure_ascii=False,
                indent=2
            )
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp, path)

    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return fallback


def roots():
    result = [
        {
            "name": "Termux Home",
            "path": HOME,
            "kind": "home"
        }
    ]

    if os.path.isdir(SHARED):
        result.append(
            {
                "name": "Shared Storage",
                "path": os.path.realpath(SHARED),
                "kind": "shared"
            }
        )

    return result


def allowed(path):
    real = os.path.realpath(path)

    for root in (
        HOME,
        os.path.realpath(SHARED)
    ):
        if real == root or real.startswith(root + os.sep):
            return real

    raise PermissionError(
        "Path outside allowed Termux roots"
    )


def safe_path(path):
    if not path:
        return HOME

    if not os.path.isabs(path):
        path = os.path.join(HOME, path)

    return allowed(path)


def rel_label(path):
    real = os.path.realpath(path)

    if real == HOME:
        return "~"

    shared = os.path.realpath(SHARED)

    if real == shared:
        return "/storage/emulated/0"

    if real.startswith(HOME + os.sep):
        return "~/" + os.path.relpath(real, HOME)

    if real.startswith(shared + os.sep):
        return "/storage/emulated/0/" + os.path.relpath(
            real,
            shared
        )

    return real


def file_icon(name, directory=False):
    if directory:
        return "fa-solid fa-folder"

    lower = name.lower()

    if lower == ".env" or lower.startswith(".env."):
        return EXTENSIONS["env"]

    ext = lower.rsplit(".", 1)[-1] if "." in lower else ""

    return EXTENSIONS.get(
        ext,
        "fa-solid fa-file"
    )


def list_directory(path):
    directory = safe_path(path)

    if not os.path.isdir(directory):
        raise FileNotFoundError(directory)

    entries = []

    with os.scandir(directory) as scan:
        for entry in scan:
            if len(entries) >= MAX_SCAN_ITEMS:
                break

            try:
                is_dir = entry.is_dir(
                    follow_symlinks=False
                )

                stat = entry.stat(
                    follow_symlinks=False
                )

                entries.append(
                    {
                        "name": entry.name,
                        "path": entry.path,
                        "type": (
                            "directory"
                            if is_dir
                            else "file"
                        ),
                        "icon": file_icon(
                            entry.name,
                            is_dir
                        ),
                        "size": (
                            stat.st_size
                            if not is_dir
                            else 0
                        ),
                        "mtime": stat.st_mtime,
                        "hidden": entry.name.startswith("."),
                        "symlink": entry.is_symlink(),
                    }
                )

            except (
                PermissionError,
                FileNotFoundError,
                OSError
            ):
                continue

    entries.sort(
        key=lambda x: (
            x["type"] != "directory",
            x["name"].lower()
        )
    )

    return entries


def is_probably_text(path):
    ext = Path(path).suffix.lower()

    text_ext = {
        ".txt",
        ".md",
        ".json",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".py",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".php",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".rs",
        ".go",
        ".sql",
        ".xml",
        ".svg",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".conf",
        ".cfg",
        ".env",
        ".gitignore",
        ".dockerignore",
        ".editorconfig",
        ".lock",
        ".log",
    }

    if (
        ext in text_ext
        or os.path.basename(path).startswith(".")
    ):
        return True

    try:
        with open(path, "rb") as handle:
            sample = handle.read(8192)

        return b"\x00" not in sample

    except Exception:
        return False


def atomic_write(path, data):
    path = safe_path(path)

    parent = os.path.dirname(path)

    os.makedirs(
        parent,
        exist_ok=True
    )

    fd, temp = tempfile.mkstemp(
        prefix=".vstemu-write-",
        dir=parent
    )

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp, path)

    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@app.get("/")
def index():
    return Response(
        PAGE,
        mimetype="text/html"
    )


@app.get("/api/roots")
def api_roots():
    return jsonify(
        {
            "roots": roots(),
            "home": HOME,
            "shared": SHARED
        }
    )


@app.get("/api/list")
def api_list():
    try:
        path = safe_path(
            request.args.get(
                "path",
                HOME
            )
        )

        return jsonify(
            {
                "path": path,
                "label": rel_label(path),
                "entries": list_directory(path)
            }
        )

    except PermissionError:
        return jsonify(
            {
                "error": "Permission denied"
            }
        ), 403

    except FileNotFoundError:
        return jsonify(
            {
                "error": "Directory not found"
            }
        ), 404

    except Exception as exc:
        return jsonify(
            {
                "error": str(exc)
            }
        ), 500


@app.get("/api/read")
def api_read():
    try:
        path = safe_path(
            request.args.get(
                "path",
                ""
            )
        )

        if not os.path.isfile(path):
            return jsonify(
                {
                    "error": "File not found"
                }
            ), 404

        size = os.path.getsize(path)

        if size > MAX_FILE_SIZE:
            return jsonify(
                {
                    "error": (
                        f"File is larger than "
                        f"{MAX_FILE_SIZE // 1024 // 1024} MB"
                    )
                }
            ), 413

        if not is_probably_text(path):
            return jsonify(
                {
                    "error": (
                        "Binary files are not opened "
                        "in the editor"
                    )
                }
            ), 415

        with open(
            path,
            "r",
            encoding="utf-8",
            errors="replace"
        ) as handle:
            content = handle.read()

        return jsonify(
            {
                "path": path,
                "content": content,
                "size": size,
                "mtime": os.path.getmtime(path)
            }
        )

    except PermissionError:
        return jsonify(
            {
                "error": "Permission denied"
            }
        ), 403

    except Exception as exc:
        return jsonify(
            {
                "error": str(exc)
            }
        ), 500


@app.put("/api/write")
def api_write():
    try:
        payload = request.get_json(force=True)

        path = safe_path(
            payload.get(
                "path",
                ""
            )
        )

        content = payload.get(
            "content",
            ""
        )

        if not isinstance(content, str):
            return jsonify(
                {
                    "error": "Content must be text"
                }
            ), 400

        data = content.encode(
            "utf-8"
        )

        if len(data) > MAX_FILE_SIZE:
            return jsonify(
                {
                    "error": "File is too large"
                }
            ), 413

        atomic_write(
            path,
            data
        )

        return jsonify(
            {
                "ok": True,
                "path": path,
                "size": len(data),
                "mtime": os.path.getmtime(path)
            }
        )

    except PermissionError:
        return jsonify(
            {
                "error": "Permission denied"
            }
        ), 403

    except Exception as exc:
        return jsonify(
            {
                "error": str(exc)
            }
        ), 500


@app.post("/api/create")
def api_create():
    try:
        payload = request.get_json(force=True)

        parent = safe_path(
            payload.get(
                "parent",
                HOME
            )
        )

        name = str(
            payload.get(
                "name",
                ""
            )
        ).strip()

        kind = payload.get(
            "type",
            "file"
        )

        if (
            not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
        ):
            return jsonify(
                {
                    "error": "Invalid name"
                }
            ), 400

        target = safe_path(
            os.path.join(
                parent,
                name
            )
        )

        if os.path.exists(target):
            return jsonify(
                {
                    "error": "Already exists"
                }
            ), 409

        if kind == "directory":
            os.makedirs(target)
        else:
            atomic_write(
                target,
                b""
            )

        return jsonify(
            {
                "ok": True,
                "path": target
            }
        )

    except PermissionError:
        return jsonify(
            {
                "error": "Permission denied"
            }
        ), 403

    except Exception as exc:
        return jsonify(
            {
                "error": str(exc)
            }
        ), 500


@app.post("/api/rename")
def api_rename():
    try:
        payload = request.get_json(force=True)

        source = safe_path(
            payload.get(
                "path",
                ""
            )
        )

        name = str(
            payload.get(
                "name",
                ""
            )
        ).strip()

        if (
            not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
        ):
            return jsonify(
                {
                    "error": "Invalid name"
                }
            ), 400

        target = safe_path(
            os.path.join(
                os.path.dirname(source),
                name
            )
        )

        if os.path.exists(target):
            return jsonify(
                {
                    "error": (
                        "A file or folder with "
                        "that name already exists"
                    )
                }
            ), 409

        os.rename(
            source,
            target
        )

        return jsonify(
            {
                "ok": True,
                "path": target
            }
        )

    except PermissionError:
        return jsonify(
            {
                "error": "Permission denied"
            }
        ), 403

    except Exception as exc:
        return jsonify(
            {
                "error": str(exc)
            }
        ), 500


@app.post("/api/delete")
def api_delete():
    try:
        payload = request.get_json(force=True)

        path = safe_path(
            payload.get(
                "path",
                ""
            )
        )

        if path in {
            HOME,
            os.path.realpath(SHARED),
            DATA_ROOT
        }:
            return jsonify(
                {
                    "error": "Protected path"
                }
            ), 403

        if (
            os.path.isdir(path)
            and not os.path.islink(path)
        ):
            shutil.rmtree(path)

        elif os.path.exists(path):
            os.remove(path)

        else:
            return jsonify(
                {
                    "error": "Not found"
                }
            ), 404

        return jsonify(
            {
                "ok": True
            }
        )

    except PermissionError:
        return jsonify(
            {
                "error": "Permission denied"
            }
        ), 403

    except Exception as exc:
        return jsonify(
            {
                "error": str(exc)
            }
        ), 500


@app.get("/api/style")
def api_style():
    style = load_json(
        STYLE_FILE,
        DEFAULT_STYLE
    )

    return jsonify(style)


@app.put("/api/style")
def api_style_write():
    payload = request.get_json(force=True)

    style = dict(DEFAULT_STYLE)

    style.update(
        {
            k: v
            for k, v in payload.items()
            if k in DEFAULT_STYLE
        }
    )

    atomic_json_write(
        STYLE_FILE,
        style
    )

    return jsonify(style)


@app.get("/api/state")
def api_state():
    return jsonify(
        load_json(
            STATE_FILE,
            {
                "openFiles": [],
                "lastFile": None
            }
        )
    )


@app.put("/api/state")
def api_state_write():
    payload = request.get_json(force=True)

    state = {
        "openFiles": payload.get(
            "openFiles",
            []
        )[-20:],
        "lastFile": payload.get(
            "lastFile"
        ),
    }

    atomic_json_write(
        STATE_FILE,
        state
    )

    return jsonify(state)


@app.get("/api/info")
def api_info():
    return jsonify(
        {
            "app": APP_NAME,
            "home": HOME,
            "shared": SHARED,
            "data": DATA_ROOT,
            "python": os.sys.version,
            "platform": os.uname().sysname,
            "cwd": os.getcwd(),
        }
    )


class TerminalSession:
    def __init__(self, ws):
        self.ws = ws
        self.pid = None
        self.fd = None
        self.closed = threading.Event()
        self.lock = threading.Lock()

    def send(self, data):
        if self.closed.is_set():
            return

        try:
            with self.lock:
                self.ws.send(data)
        except Exception:
            self.closed.set()

    def start(self):
        master, slave = os.openpty()

        self.fd = master

        shell = (
            os.environ.get("SHELL")
            or os.path.join(
                os.environ.get(
                    "PREFIX",
                    "/data/data/com.termux/files/usr"
                ),
                "bin",
                "bash"
            )
        )

        env = os.environ.copy()

        env.update(
            {
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "TERM_PROGRAM": "vstermu",
                "LANG": env.get(
                    "LANG",
                    "C.UTF-8"
                ),
            }
        )

        self.pid = os.fork()

        if self.pid == 0:
            try:
                os.setsid()

                fcntl.ioctl(
                    slave,
                    termios.TIOCSCTTY,
                    0
                )

                os.dup2(slave, 0)
                os.dup2(slave, 1)
                os.dup2(slave, 2)

                if slave > 2:
                    os.close(slave)

                if master > 2:
                    os.close(master)

                os.chdir(HOME)

                os.execvpe(
                    shell,
                    [
                        shell,
                        "-l"
                    ],
                    env
                )

            except Exception:
                os._exit(127)

        os.close(slave)

        self.set_size(
            100,
            30
        )

        threading.Thread(
            target=self.reader,
            daemon=True
        ).start()

    def reader(self):
        while not self.closed.is_set():
            try:
                ready, _, _ = select.select(
                    [self.fd],
                    [],
                    [],
                    0.25
                )

                if not ready:
                    continue

                data = os.read(
                    self.fd,
                    65536
                )

                if not data:
                    break

                self.send(
                    data.decode(
                        "utf-8",
                        errors="replace"
                    )
                )

            except (
                OSError,
                ValueError
            ):
                break

        self.closed.set()

    def write(self, data):
        if (
            self.closed.is_set()
            or self.fd is None
        ):
            return

        try:
            os.write(
                self.fd,
                data.encode(
                    "utf-8",
                    errors="replace"
                )
            )
        except OSError:
            self.closed.set()

    def set_size(self, cols, rows):
        if self.fd is None:
            return

        try:
            packed = struct.pack(
                "HHHH",
                int(rows),
                int(cols),
                0,
                0
            )

            fcntl.ioctl(
                self.fd,
                termios.TIOCSWINSZ,
                packed
            )

            if self.pid:
                os.kill(
                    self.pid,
                    signal.SIGWINCH
                )

        except OSError:
            pass

    def close(self):
        if self.closed.is_set():
            return

        self.closed.set()

        try:
            if self.pid:
                os.kill(
                    self.pid,
                    signal.SIGHUP
                )
        except OSError:
            pass

        try:
            if self.fd is not None:
                os.close(self.fd)
        except OSError:
            pass


@sock.route("/ws/terminal")
def terminal(ws):
    session = TerminalSession(ws)

    session.start()

    try:
        while not session.closed.is_set():
            message = ws.receive()

            if message is None:
                break

            if isinstance(message, bytes):
                message = message.decode(
                    "utf-8",
                    errors="replace"
                )

            try:
                packet = json.loads(message)
            except Exception:
                packet = {
                    "type": "input",
                    "data": message
                }

            kind = packet.get("type")

            if kind == "input":
                session.write(
                    packet.get(
                        "data",
                        ""
                    )
                )

            elif kind == "resize":
                session.set_size(
                    packet.get(
                        "cols",
                        100
                    ),
                    packet.get(
                        "rows",
                        30
                    )
                )

            elif kind == "cwd":
                path = safe_path(
                    packet.get(
                        "path",
                        HOME
                    )
                )

                if os.path.isdir(path):
                    command = (
                        "cd -- "
                        + shell_quote(path)
                        + "\n"
                    )

                    session.write(command)

    except Exception:
        pass

    finally:
        session.close()


def shell_quote(value):
    return "'" + value.replace(
        "'",
        "'\\''"
    ) + "'"


PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="theme-color" content="#0b0d10">
<title>vstermu PRO</title>
<link rel="icon" href="https://raw.githubusercontent.com/joaoTYSM/VStermu/refs/heads/main/icon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fira+Code:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/7.0.0/css/all.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/codemirror.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/theme/material-darker.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/theme/dracula.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/theme/eclipse.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css">

<style>
:root{
--bg:#0b0d10;
--panel:#111418;
--panel2:#15191e;
--border:#252b32;
--text:#e7eaf0;
--muted:#858d99;
--accent:#55d98b;
--accent2:#35a86b;
--danger:#ff6262;
--blue:#63a4ff;
--shadow:0 18px 50px #0008;
--sidebar:280px;
--term:280px;
--editor-size:14px;
--radius:10px
}

[data-theme=light]{
--bg:#f5f6f8;
--panel:#fff;
--panel2:#f0f2f5;
--border:#d9dde4;
--text:#16191e;
--muted:#69717d;
--accent:#15803d;
--accent2:#166534;
--danger:#dc2626;
--blue:#2563eb
}

[data-theme=dracula]{
--bg:#282a36;
--panel:#21222c;
--panel2:#191a21;
--border:#44475a;
--text:#f8f8f2;
--muted:#8b91ad;
--accent:#50fa7b;
--accent2:#37d35e;
--danger:#ff5555;
--blue:#8be9fd
}

*{
box-sizing:border-box;
-webkit-tap-highlight-color:transparent
}

html,body{
height:100%;
margin:0;
overflow:hidden
}

body{
font-family:Inter,sans-serif;
background:var(--bg);
color:var(--text);
font-size:14px
}

button,input,select{
font:inherit;
color:inherit
}

button{
border:0;
background:none
}

#app{
height:100%;
display:grid;
grid-template-rows:52px 1fr
}

.topbar{
height:52px;
background:var(--panel);
border-bottom:1px solid var(--border);
display:flex;
align-items:center;
justify-content:space-between;
padding:0 12px;
z-index:30
}

.brand{
display:flex;
align-items:center;
gap:9px;
font-weight:700;
white-space:nowrap
}

.brand img{
width:27px;
height:27px
}

.brand small{
font-weight:500;
color:var(--muted);
font-size:10px
}

.top-actions{
display:flex;
align-items:center;
gap:5px
}

.icon-btn,.top-btn{
height:34px;
min-width:34px;
padding:0 9px;
border:1px solid var(--border);
border-radius:8px;
background:var(--panel2);
cursor:pointer
}

.icon-btn:active,.top-btn:active{
transform:scale(.97)
}

.top-btn{
display:flex;
gap:7px;
align-items:center
}

.status-dot{
width:7px;
height:7px;
border-radius:50%;
background:var(--accent);
box-shadow:0 0 10px var(--accent)
}

.workspace{
min-height:0;
display:grid;
grid-template-columns:var(--sidebar) minmax(0,1fr);
position:relative
}

.sidebar{
background:var(--panel);
border-right:1px solid var(--border);
min-width:0;
display:flex;
flex-direction:column;
z-index:20
}

.sidebar-head{
height:42px;
display:flex;
align-items:center;
justify-content:space-between;
padding:0 10px;
border-bottom:1px solid var(--border)
}

.section-title{
font-size:11px;
letter-spacing:.08em;
text-transform:uppercase;
color:var(--muted);
font-weight:700
}

.sidebar-tools{
display:flex;
gap:2px
}

.small-btn{
width:30px;
height:30px;
border-radius:7px;
color:var(--muted);
cursor:pointer
}

.small-btn:hover{
background:var(--panel2);
color:var(--text)
}

.roots{
border-bottom:1px solid var(--border);
padding:5px
}

.root{
height:31px;
border-radius:6px;
display:flex;
align-items:center;
gap:8px;
padding:0 8px;
color:var(--muted);
cursor:pointer;
font-size:12px
}

.root.active,.root:hover{
background:var(--panel2);
color:var(--text)
}

.tree{
flex:1;
overflow:auto;
padding:5px 4px 60px
}

.tree-row{
height:32px;
display:flex;
align-items:center;
gap:7px;
border-radius:6px;
cursor:pointer;
padding-right:5px;
user-select:none;
position:relative
}

.tree-row:hover{
background:var(--panel2)
}

.tree-row.selected{
background:#ffffff0d;
box-shadow:inset 2px 0 var(--accent)
}

.tree-row .arrow{
width:14px;
text-align:center;
color:var(--muted);
font-size:10px
}

.tree-row .name{
min-width:0;
overflow:hidden;
text-overflow:ellipsis;
white-space:nowrap;
flex:1
}

.tree-row .meta{
font-size:9px;
color:var(--muted)
}

.tree-row i.file-icon{
width:17px;
text-align:center;
color:#9da7b5
}

.tree-row.dir i.file-icon{
color:#e3b765
}

.tree-empty{
padding:20px;
color:var(--muted);
font-size:12px;
text-align:center
}

.main{
min-width:0;
min-height:0;
display:grid;
grid-template-rows:minmax(180px,1fr) var(--term);
position:relative
}

.editor{
min-width:0;
min-height:0;
display:flex;
flex-direction:column;
background:var(--bg)
}

.tabs{
height:39px;
display:flex;
align-items:center;
background:var(--panel);
border-bottom:1px solid var(--border);
overflow:auto
}

.tab{
height:39px;
display:flex;
align-items:center;
gap:8px;
padding:0 12px;
border-right:1px solid var(--border);
color:var(--muted);
font-size:12px;
white-space:nowrap;
cursor:pointer
}

.tab.active{
color:var(--text);
background:var(--bg)
}

.tab-close{
font-size:11px;
color:var(--muted)
}

.editor-tools{
margin-left:auto;
display:flex;
gap:2px;
padding:0 4px;
position:sticky;
right:0;
background:var(--panel)
}

.editor-wrap{
position:relative;
flex:1;
min-height:0
}

.CodeMirror{
height:100%;
font-family:'Fira Code',monospace;
font-size:var(--editor-size);
line-height:1.55
}

.CodeMirror-gutters{
background:var(--panel)!important;
border-right:1px solid var(--border)!important
}

.CodeMirror-linenumber{
color:#68717c
}

.empty-editor{
position:absolute;
inset:0;
display:flex;
align-items:center;
justify-content:center;
flex-direction:column;
color:var(--muted);
gap:10px;
z-index:2;
background:var(--bg)
}

.empty-editor img{
width:55px;
opacity:.6
}

.empty-editor b{
color:var(--text);
font-size:15px
}

.hidden{
display:none!important
}

.terminal{
min-height:0;
background:#070909;
color:#dce8df;
border-top:1px solid var(--border);
display:flex;
flex-direction:column
}

.term-head{
height:34px;
background:var(--panel);
display:flex;
align-items:center;
padding:0 8px;
border-bottom:1px solid var(--border);
flex-shrink:0
}

.term-title{
display:flex;
align-items:center;
gap:7px;
font-size:11px;
color:var(--muted)
}

.term-actions{
margin-left:auto;
display:flex;
gap:2px
}

.xterm{
height:100%;
padding:7px 9px
}

.xterm .xterm-viewport{
background:#070909!important
}

.terminal.minimized .term-body{
display:none
}

.terminal.minimized{
height:34px
}

.terminal.minimized .term-head{
border-bottom:0
}

.terminal-body{
min-height:0;
flex:1
}

.overlay{
position:fixed;
inset:0;
background:#0007;
backdrop-filter:blur(4px);
z-index:100;
display:none;
align-items:center;
justify-content:center;
padding:15px
}

.overlay.open{
display:flex
}

.modal{
width:min(440px,100%);
max-height:90vh;
overflow:auto;
background:var(--panel);
border:1px solid var(--border);
border-radius:14px;
box-shadow:var(--shadow)
}

.modal-head{
padding:15px 16px;
border-bottom:1px solid var(--border);
display:flex;
align-items:center;
justify-content:space-between
}

.modal-title{
font-weight:700
}

.modal-body{
padding:16px
}

.modal-row{
display:flex;
flex-direction:column;
gap:6px;
margin-bottom:14px
}

.modal-row label{
font-size:11px;
color:var(--muted)
}

.modal-row input,.modal-row select{
width:100%;
height:39px;
background:var(--bg);
border:1px solid var(--border);
border-radius:8px;
padding:0 11px;
outline:0
}

.modal-row input:focus,.modal-row select:focus{
border-color:var(--accent)
}

.modal-foot{
display:flex;
justify-content:flex-end;
gap:8px;
padding:12px 16px;
border-top:1px solid var(--border)
}

.btn{
height:36px;
border-radius:8px;
padding:0 13px;
background:var(--panel2);
border:1px solid var(--border);
cursor:pointer
}

.btn.primary{
background:var(--accent2);
border-color:var(--accent2);
color:#fff
}

.btn.danger{
color:#fff;
background:var(--danger);
border-color:var(--danger)
}

.context{
position:fixed;
z-index:200;
width:235px;
background:var(--panel);
border:1px solid var(--border);
border-radius:12px;
box-shadow:var(--shadow);
padding:6px;
display:none
}

.context.open{
display:block
}

.context button{
width:100%;
height:37px;
border-radius:7px;
display:flex;
align-items:center;
gap:10px;
padding:0 10px;
text-align:left;
cursor:pointer
}

.context button:hover{
background:var(--panel2)
}

.context button.danger{
color:var(--danger)
}

.context hr{
border:0;
border-top:1px solid var(--border);
margin:5px 0
}

.toast{
position:fixed;
left:50%;
bottom:18px;
transform:translate(-50%,20px);
background:var(--panel);
border:1px solid var(--border);
box-shadow:var(--shadow);
padding:10px 14px;
border-radius:9px;
color:var(--text);
font-size:12px;
opacity:0;
pointer-events:none;
transition:.2s;
z-index:300
}

.toast.show{
opacity:1;
transform:translate(-50%,0)
}

.backdrop{
display:none;
position:fixed;
inset:0;
background:#0006;
z-index:15
}

.backdrop.show{
display:block
}

.loading{
position:absolute;
right:15px;
top:12px;
font-size:10px;
color:var(--muted)
}

@media(max-width:800px){

#app{
grid-template-rows:48px 1fr
}

.topbar{
height:48px;
padding:0 8px
}

.brand small{
display:none
}

.top-btn span{
display:none
}

.top-btn{
padding:0;
width:34px;
justify-content:center
}

.workspace{
grid-template-columns:1fr
}

.sidebar{
position:absolute;
left:0;
top:0;
bottom:0;
width:min(86vw,310px);
transform:translateX(-102%);
transition:transform .2s;
box-shadow:var(--shadow);
z-index:20
}

.sidebar.open{
transform:translateX(0)
}

.main{
grid-template-rows:minmax(160px,1fr) var(--term)
}

.tabs{
height:36px
}

.tab{
height:36px;
padding:0 9px
}

.editor-tools{
padding-right:3px
}

.CodeMirror{
font-size:var(--editor-size)
}

.terminal{
border-top:1px solid var(--border)
}

.tree-row{
height:38px
}

.root{
height:36px
}

.context{
width:min(260px,calc(100vw - 20px))
}

.modal{
border-radius:13px
}

}

@media(max-width:480px){

.main{
grid-template-rows:minmax(145px,1fr) var(--term)
}

.term-head{
height:32px
}

.xterm{
padding:4px
}

.brand{
font-size:14px
}

.brand img{
width:24px;
height:24px
}

}
</style>
</head>

<body>

<div id="app">

<header class="topbar">

<div class="brand">
<img src="https://raw.githubusercontent.com/joaoTYSM/VStermu/refs/heads/main/icon.svg">
<span>vstermu</span>
<small>PRO</small>
<span class="status-dot" id="statusDot"></span>
</div>

<div class="top-actions">

<button class="icon-btn"
id="menuBtn"
title="Explorer">
<i class="fa-solid fa-bars"></i>
</button>

<button class="icon-btn"
id="saveBtn"
title="Save">
<i class="fa-solid fa-floppy-disk"></i>
</button>

<button class="icon-btn"
id="settingsBtn"
title="Settings">
<i class="fa-solid fa-gear"></i>
</button>

</div>

</header>

<div class="workspace">

<aside class="sidebar" id="sidebar">

<div class="sidebar-head">

<span class="section-title">
Explorer
</span>

<div class="sidebar-tools">

<button
class="small-btn"
id="newFileBtn"
title="New file">
<i class="fa-solid fa-file-circle-plus"></i>
</button>

<button
class="small-btn"
id="newFolderBtn"
title="New folder">
<i class="fa-solid fa-folder-plus"></i>
</button>

<button
class="small-btn"
id="refreshBtn"
title="Refresh">
<i class="fa-solid fa-rotate"></i>
</button>

</div>

</div>

<div class="roots" id="roots"></div>

<div class="tree" id="tree">
<div class="tree-empty">
Loading filesystem...
</div>
</div>

</aside>

<div
class="backdrop"
id="backdrop">
</div>

<main class="main">

<section class="editor">

<div class="tabs" id="tabs">

<div class="tab">
<i class="fa-solid fa-code"></i>
<span>No file open</span>
</div>

<div class="editor-tools">

<button
class="small-btn"
id="fileConfigBtn"
title="File settings">

<i class="fa-solid fa-sliders"></i>

</button>

</div>

</div>

<div class="editor-wrap">

<textarea id="editor"></textarea>

<div
class="empty-editor"
id="emptyEditor">

<img src="https://raw.githubusercontent.com/joaoTYSM/VStermu/refs/heads/main/icon.svg">

<b>Select a file to edit</b>

<span>
Files are loaded only when opened.
</span>

</div>

<span
class="loading hidden"
id="editorLoading">
Loading...
</span>

</div>

</section>

<section
class="terminal"
id="terminalPanel">

<div class="term-head">

<div class="term-title">

<i class="fa-solid fa-terminal"></i>

<span>
Termux terminal
</span>

<span id="termState">
connecting
</span>

</div>

<div class="term-actions">

<button
class="small-btn"
id="clearTermBtn"
title="Clear">

<i class="fa-solid fa-broom"></i>

</button>

<button
class="small-btn"
id="minTermBtn"
title="Minimize">

<i class="fa-solid fa-chevron-down"></i>

</button>

</div>

</div>

<div
class="terminal-body"
id="terminalBody">
</div>

</section>

</main>

</div>

</div>

<div
class="context"
id="contextMenu">

<button data-action="open">
<i class="fa-solid fa-pen-to-square"></i>
Open
</button>

<button data-action="rename">
<i class="fa-solid fa-i-cursor"></i>
Rename
</button>

<button data-action="file">
<i class="fa-solid fa-file-circle-plus"></i>
Add file
</button>

<button data-action="folder">
<i class="fa-solid fa-folder-plus"></i>
Add folder
</button>

<button data-action="terminal">
<i class="fa-solid fa-terminal"></i>
Open terminal here
</button>

<hr>

<button
data-action="delete"
class="danger">

<i class="fa-solid fa-trash"></i>
Delete

</button>

</div>

<div
class="overlay"
id="modalOverlay">

<div class="modal">

<div class="modal-head">

<span
class="modal-title"
id="modalTitle">
Action
</span>

<button
class="small-btn"
id="modalClose">

<i class="fa-solid fa-xmark"></i>

</button>

</div>

<div
class="modal-body"
id="modalBody">
</div>

<div class="modal-foot">

<button
class="btn"
id="modalCancel">
Cancel
</button>

<button
class="btn primary"
id="modalConfirm">
Confirm
</button>

</div>

</div>

</div>

<div
class="toast"
id="toast">
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/codemirror.min.js"></script>

<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/javascript/javascript.min.js"></script>

<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/xml/xml.min.js"></script>

<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/css/css.min.js"></script>

<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/htmlmixed/htmlmixed.min.js"></script>

<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/python/python.min.js"></script>

<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/shell/shell.min.js"></script>

<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/markdown/markdown.min.js"></script>

<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/clike/clike.min.js"></script>

<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js"></script>

<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js"></script>

<script>

const $=id=>document.getElementById(id);

const api=(url,options={})=>
fetch(
url,
{
headers:{
'Content-Type':'application/json'
},
...options
}
)
.then(
async r=>{
const d=await r.json().catch(
()=>({})
);

if(!r.ok)
throw Error(
d.error||`HTTP ${r.status}`
);

return d;
}
);

let style={};

let roots=[];

let currentRoot=null;

let openDirs=new Set();

let selectedPath=null;

let selectedType=null;

let currentFile=null;

let currentParent=null;

let saveTimer=null;

let longTimer=null;

let longTriggered=false;

let modalAction=null;

const editor=CodeMirror.fromTextArea(
$('editor'),
{
lineNumbers:true,
theme:'material-darker',
mode:'javascript',
indentUnit:4,
tabSize:4,
lineWrapping:true,
viewportMargin:40,
matchBrackets:true,
autoCloseBrackets:true
}
);

const term=new Terminal(
{
cursorBlink:true,
convertEol:true,
scrollback:5000,
fontFamily:'Fira Code,monospace',
fontSize:14,
theme:{
background:'#070909',
foreground:'#dce8df',
cursor:'#55d98b',
selectionBackground:'#28553b'
}
}
);

const fitAddon=new FitAddon.FitAddon();

term.loadAddon(
fitAddon
);

term.open(
$('terminalBody')
);

function toast(message){

$('toast').textContent=message;

$('toast').classList.add(
'show'
);

clearTimeout(
window.toastTimer
);

window.toastTimer=setTimeout(
()=>$('toast').classList.remove(
'show'
),
2200
);

}

function icon(name){

return `<i class="${name}"></i>`;

}

function escapeHtml(s){

return String(s).replace(
/[&<>'"]/g,
c=>({
'&':'&amp;',
'<':'&lt;',
'>':'&gt;',
"'":'&#39;',
'"':'&quot;'
}[c])
);

}

function formatSize(n){

if(n<1024)
return n+' B';

if(n<1048576)
return (n/1024).toFixed(1)+' KB';

return (n/1048576).toFixed(1)+' MB';

}

function modeFor(path){

const e=
path.split('.')
.pop()
.toLowerCase();

return ({
js:'javascript',
mjs:'javascript',
cjs:'javascript',
ts:'javascript',
jsx:'javascript',
tsx:'javascript',
html:'htmlmixed',
htm:'htmlmixed',
css:'css',
scss:'css',
py:'python',
sh:'shell',
bash:'shell',
zsh:'shell',
md:'markdown',
json:{
name:'javascript',
json:true
},
xml:'xml',
svg:'xml',
c:'text/x-csrc',
cpp:'text/x-c++src',
h:'text/x-csrc',
hpp:'text/x-c++src',
java:'text/x-java',
rs:'text/x-rust',
go:'text/x-go'
}[e]||'text/plain');

}

function themeMode(){

return style.theme==='light'
?'eclipse'
:style.theme==='dracula'
?'dracula'
:'material-darker';

}

function applyStyle(){

document.body.dataset.theme=
style.theme||'dark';

document.documentElement.style.setProperty(
'--sidebar',
(style.sidebarWidth||280)+'px'
);

document.documentElement.style.setProperty(
'--term',
(style.terminalHeight||280)+'px'
);

document.documentElement.style.setProperty(
'--editor-size',
(style.editorFontSize||14)+'px'
);

editor.setOption(
'theme',
themeMode()
);

editor.setOption(
'lineWrapping',
style.wordWrap!==false
);

term.options.fontSize=
style.terminalFontSize||14;

try{
fitAddon.fit();
}catch(e){}

}

async function loadStyle(){

style=await api(
'/api/style'
);

applyStyle();

}

async function loadRoots(){

const d=await api(
'/api/roots'
);

roots=d.roots;

$('roots').innerHTML='';

roots.forEach(
(r,i)=>{

const el=
document.createElement(
'div'
);

el.className='root';

el.innerHTML=
icon(
r.kind==='home'
?'fa-solid fa-house'
:'fa-solid fa-hard-drive'
)
+
'<span>'
+
escapeHtml(r.name)
+
'</span>';

el.onclick=
()=>selectRoot(r);

$('roots').appendChild(
el
);

if(i===0)
selectRoot(r);

}
);

}

async function selectRoot(root){

currentRoot=root;

document
.querySelectorAll('.root')
.forEach(
x=>x.classList.remove(
'active'
)
);

[
...document.querySelectorAll(
'.root'
)
]
.find(
x=>x.textContent===root.name
)?.classList.add(
'active'
);

openDirs=
new Set(
[root.path]
);

selectedPath=
root.path;

selectedType=
'directory';

await renderTree();

}

async function renderTree(){

if(!currentRoot)
return;

$('tree').innerHTML=
'<div class="tree-empty">Loading...</div>';

try{

const html=
await buildDir(
currentRoot.path,
0
);

$('tree').innerHTML=
html||
'<div class="tree-empty">Empty directory</div>';

bindTree();

}catch(e){

$('tree').innerHTML=
'<div class="tree-empty">'
+
escapeHtml(e.message)
+
'</div>';

}

}

async function buildDir(path,depth){

let d;

try{

d=await api(
'/api/list?path='
+
encodeURIComponent(path)
);

}catch(e){

return `
<div class="tree-empty">
${escapeHtml(e.message)}
</div>
`;

}

let html='';

for(
const item of d.entries
){

const pad=
8+
depth*17;

const isDir=
item.type==='directory';

const expanded=
openDirs.has(
item.path
);

html+=
`
<div
class="tree-row ${isDir?'dir':''} ${selectedPath===item.path?'selected':''}"
data-path="${encodeURIComponent(item.path)}"
data-type="${item.type}"
style="padding-left:${pad}px">

${
isDir
?`<span class="arrow">${expanded?'▾':'▸'}</span>`
:'<span class="arrow"></span>'
}

<i class="file-icon ${item.icon}"></i>

<span class="name">
${escapeHtml(item.name)}
</span>

${
!isDir
?`<span class="meta">${formatSize(item.size)}</span>`
:''
}

</div>
`;

if(
isDir&&
expanded
){

html+=
await buildDir(
item.path,
depth+1
);

}

}

return html;

}

function bindTree(){

document
.querySelectorAll('.tree-row')
.forEach(
row=>{

const path=
decodeURIComponent(
row.dataset.path
);

const type=
row.dataset.type;

row.addEventListener(
'click',
e=>{

if(longTriggered){

longTriggered=false;

return;

}

selectedPath=path;

selectedType=type;

if(type==='directory'){

if(openDirs.has(path))
openDirs.delete(path);
else
openDirs.add(path);

renderTree();

}else{

openFile(path);

}

}
);

row.addEventListener(
'contextmenu',
e=>{

e.preventDefault();

selectedPath=path;

selectedType=type;

showContext(
e.clientX,
e.clientY
);

}
);

row.addEventListener(
'touchstart',
e=>{

longTriggered=false;

longTimer=
setTimeout(
()=>{

longTriggered=true;

selectedPath=path;

selectedType=type;

const t=
e.touches[0];

showContext(
t.clientX,
t.clientY
);

},
550
);

},
{
passive:true
}
);

row.addEventListener(
'touchend',
()=>clearTimeout(
longTimer
)
);

row.addEventListener(
'touchmove',
()=>clearTimeout(
longTimer
)
);

}
);

}

async function openFile(path){

$('editorLoading')
.classList.remove(
'hidden'
);

$('emptyEditor')
.classList.add(
'hidden'
);

try{

const d=
await api(
'/api/read?path='+
encodeURIComponent(path)
);

currentFile=path;

currentParent=
path.substring(
0,
path.lastIndexOf('/')
)||'/';

editor.setOption(
'mode',
modeFor(path)
);

editor.setValue(
d.content
);

editor.clearHistory();

$('tabs').innerHTML=
`
<div class="tab active">
${icon(fileIconClient(path))}
<span>${escapeHtml(path.split('/').pop())}</span>
<span class="tab-close" id="closeFile">×</span>
</div>

<div class="editor-tools">

<button
class="small-btn"
id="fileConfigBtn"
title="File settings">

<i class="fa-solid fa-sliders"></i>

</button>

</div>
`;

$('closeFile').onclick=
closeFile;

$('fileConfigBtn').onclick=
fileSettings;

editor.focus();

saveState();

toast(
'Loaded '
+
path.split('/').pop()
);

}catch(e){

toast(
e.message
);

}finally{

$('editorLoading')
.classList.add(
'hidden'
);

}

}

function fileIconClient(path){

const e=
path.split('/')
.pop()
.toLowerCase();

if(
e==='.env'||
e.startsWith('.env.')
)
return 'fa-solid fa-gears';

const ext=
e.includes('.')
?e.split('.').pop()
:'';

return {
js:'fa-brands fa-js',
ts:'fa-brands fa-js',
jsx:'fa-brands fa-react',
tsx:'fa-brands fa-react',
html:'fa-brands fa-html5',
css:'fa-brands fa-css3-alt',
py:'fa-brands fa-python',
md:'fa-brands fa-markdown',
json:'fa-solid fa-file-code',
svg:'fa-solid fa-bezier-curve',
sh:'fa-solid fa-terminal'
}[ext]
||
'fa-solid fa-file';

}

function closeFile(){

currentFile=null;

editor.setValue('');

$('emptyEditor')
.classList.remove(
'hidden'
);

$('tabs').innerHTML=
`
<div class="tab">
${icon('fa-solid fa-code')}
<span>No file open</span>
</div>

<div class="editor-tools">

<button
class="small-btn"
id="fileConfigBtn">

<i class="fa-solid fa-sliders"></i>

</button>

</div>
`;

$('fileConfigBtn').onclick=
fileSettings;

}

function saveFile(){

if(!currentFile)
return;

api(
'/api/write',
{
method:'PUT',
body:JSON.stringify(
{
path:currentFile,
content:editor.getValue()
}
)
}
)
.then(
()=>{
toast('Saved');
renderTree();
saveState();
}
)
.catch(
e=>toast(e.message)
);

}

editor.on(
'change',
()=>{

if(!currentFile)
return;

clearTimeout(
saveTimer
);

saveTimer=
setTimeout(
saveFile,
650
);

}
);

async function saveState(){

try{

await api(
'/api/state',
{
method:'PUT',
body:JSON.stringify(
{
openFiles:
currentFile
?[currentFile]
:[],
lastFile:
currentFile
}
)
}
);

}catch(e){}

}

function showContext(x,y){

const menu=
$('contextMenu');

menu.classList.add(
'open'
);

const w=
menu.offsetWidth;

const h=
menu.offsetHeight;

menu.style.left=
Math.min(
x,
innerWidth-w-8
)+'px';

menu.style.top=
Math.min(
y,
innerHeight-h-8
)+'px';

menu
.querySelectorAll(
'[data-action]'
)
.forEach(
b=>b.style.display='flex'
);

if(
selectedType==='file'
){

menu
.querySelector(
'[data-action=terminal]'
)
.style.display='none';

}else{

menu
.querySelector(
'[data-action=open]'
)
.style.display='flex';

}

}

function hideContext(){

$('contextMenu')
.classList.remove(
'open'
);

}

document.addEventListener(
'click',
e=>{
if(
!e.target.closest(
'#contextMenu'
)
)
hideContext();
}
);

$('contextMenu').addEventListener(
'click',
e=>{

const b=
e.target.closest(
'[data-action]'
);

if(!b)
return;

const a=
b.dataset.action;

hideContext();

if(a==='open'){

selectedType==='directory'
?
(
openDirs.add(
selectedPath
),
renderTree()
)
:
openFile(
selectedPath
);

}
else if(a==='rename')
renameSelected();

else if(a==='file')
createItem('file');

else if(a==='folder')
createItem('directory');

else if(a==='terminal')
terminalHere();

else if(a==='delete')
deleteSelected();

}
);

function parentForNew(){

if(
selectedType==='directory'
)
return selectedPath;

if(selectedPath)
return (
selectedPath.substring(
0,
selectedPath.lastIndexOf('/')
)
||
HOME
);

return currentRoot?.path||HOME;

}

function createItem(type){

openModal(
type==='file'
?'New file'
:'New folder',

`
<div class="modal-row">

<label>
Parent
</label>

<input
id="modalParent"
value="${escapeHtml(parentForNew())}"
disabled>

</div>

<div class="modal-row">

<label>
Name
</label>

<input
id="modalName"
placeholder="${type==='file'?'script.py':'folder'}"
autofocus>

</div>
`,

async()=>{

const name=
$('modalName')
.value
.trim();

if(!name)
return;

const d=
await api(
'/api/create',
{
method:'POST',
body:JSON.stringify(
{
parent:
parentForNew(),
name,
type
}
)
}
);

closeModal();

selectedPath=
d.path;

selectedType=
type==='directory'
?'directory'
:'file';

openDirs.add(
parentForNew()
);

await renderTree();

toast(
'Created '+name
);

if(
type==='file'
)
openFile(
d.path
);

}
);

setTimeout(
()=>$('modalName')?.focus(),
60
);

}

function renameSelected(){

if(!selectedPath)
return;

const old=
selectedPath
.split('/')
.pop();

openModal(
'Rename',

`
<div class="modal-row">

<label>
Current name
</label>

<input
value="${escapeHtml(old)}"
disabled>

</div>

<div class="modal-row">

<label>
New name
</label>

<input
id="modalName"
value="${escapeHtml(old)}">

</div>
`,

async()=>{

const name=
$('modalName')
.value
.trim();

if(!name)
return;

const oldPath=
selectedPath;

const d=
await api(
'/api/rename',
{
method:'POST',
body:JSON.stringify(
{
path:oldPath,
name
}
)
}
);

if(
currentFile===oldPath
){
currentFile=d.path;
}

selectedPath=
d.path;

await renderTree();

closeModal();

toast('Renamed');

}
);

setTimeout(
()=>$('modalName')?.focus(),
60
);

}

function deleteSelected(){

if(
!selectedPath||
selectedPath===currentRoot?.path
)
return;

openModal(
'Delete',

`
<div style="color:var(--danger);font-size:13px;line-height:1.5">

Delete
<b>
${escapeHtml(selectedPath)}
</b>?

<br>

This action cannot be undone.

</div>
`,

async()=>{

await api(
'/api/delete',
{
method:'POST',
body:JSON.stringify(
{
path:selectedPath
}
)
}
);

if(
currentFile===selectedPath
)
closeFile();

selectedPath=
currentRoot.path;

await renderTree();

closeModal();

toast('Deleted');

},
true
);

}

function fileSettings(){

if(!currentFile){

toast(
'No file selected'
);

return;

}

renameSelected();

}

function terminalHere(){

if(!selectedPath)
return;

const path=
selectedType==='directory'
?
selectedPath
:
selectedPath.substring(
0,
selectedPath.lastIndexOf('/')
);

sendWS(
{
type:'cwd',
path
}
);

$('terminalPanel')
.classList.remove(
'minimized'
);

fitTerminal();

toast(
'Terminal changed to '+path
);

}

function openModal(
title,
body,
action,
danger=false
){

modalAction=action;

$('modalTitle')
.textContent=title;

$('modalBody')
.innerHTML=body;

$('modalConfirm')
.textContent=
danger
?'Delete'
:'Confirm';

$('modalConfirm')
.className=
'btn '
+
(
danger
?'danger'
:'primary'
);

$('modalOverlay')
.classList.add(
'open'
);

}

function closeModal(){

$('modalOverlay')
.classList.remove(
'open'
);

modalAction=null;

}

$('modalConfirm').onclick=
async()=>{

if(!modalAction)
return;

try{

await modalAction();

}catch(e){

toast(
e.message
);

}

};

$('modalCancel').onclick=
closeModal;

$('modalClose').onclick=
closeModal;

$('modalOverlay').addEventListener(
'click',
e=>{
if(
e.target===
$('modalOverlay')
)
closeModal();
}
);

$('newFileBtn').onclick=
()=>createItem('file');

$('newFolderBtn').onclick=
()=>createItem('directory');

$('refreshBtn').onclick=
renderTree;

$('saveBtn').onclick=
saveFile;

$('fileConfigBtn').onclick=
fileSettings;

$('menuBtn').onclick=
()=>{

$('sidebar')
.classList.toggle(
'open'
);

$('backdrop')
.classList.toggle(
'show'
);

};

$('backdrop').onclick=
()=>{

$('sidebar')
.classList.remove(
'open'
);

$('backdrop')
.classList.remove(
'show'
);

};

$('clearTermBtn').onclick=
()=>term.clear();

$('minTermBtn').onclick=
()=>{

$('terminalPanel')
.classList.toggle(
'minimized'
);

$('minTermBtn')
.innerHTML=
$('terminalPanel')
.classList.contains(
'minimized'
)
?
icon(
'fa-solid fa-chevron-up'
)
:
icon(
'fa-solid fa-chevron-down'
);

setTimeout(
fitTerminal,
80
);

};

function openSettings(){

openModal(
'Settings',

`
<div class="modal-row">

<label>
Theme
</label>

<select id="setTheme">

<option value="dark">
Dark
</option>

<option value="dracula">
Dracula
</option>

<option value="light">
Light
</option>

</select>

</div>

<div class="modal-row">

<label>
Editor font size
</label>

<input
id="setEditor"
type="number"
min="10"
max="24"
value="${style.editorFontSize||14}">

</div>

<div class="modal-row">

<label>
Terminal font size
</label>

<input
id="setTerm"
type="number"
min="10"
max="24"
value="${style.terminalFontSize||14}">

</div>

<div class="modal-row">

<label>
Terminal height
</label>

<input
id="setHeight"
type="number"
min="120"
max="700"
value="${style.terminalHeight||280}">

</div>

<div class="modal-row">

<label>
Sidebar width
</label>

<input
id="setSide"
type="number"
min="220"
max="450"
value="${style.sidebarWidth||280}">

</div>

<div class="modal-row">

<label>
Word wrap
</label>

<select id="setWrap">

<option value="true">
Enabled
</option>

<option value="false">
Disabled
</option>

</select>

</div>
`,

async()=>{

style.theme=
$('setTheme').value;

style.editorFontSize=
+$('setEditor').value;

style.terminalFontSize=
+$('setTerm').value;

style.terminalHeight=
+$('setHeight').value;

style.sidebarWidth=
+$('setSide').value;

style.wordWrap=
$('setWrap').value==='true';

await api(
'/api/style',
{
method:'PUT',
body:JSON.stringify(style)
}
);

applyStyle();

closeModal();

toast(
'Settings saved'
);

}
);

$('setTheme').value=
style.theme;

$('setWrap').value=
String(
style.wordWrap!==false
);

}

$('settingsBtn').onclick=
openSettings;

let ws=null;

let reconnectTimer=null;

function sendWS(packet){

if(
ws&&
ws.readyState===1
)
ws.send(
JSON.stringify(packet)
);

}

function connectTerminal(){

const proto=
location.protocol==='https:'
?'wss'
:'ws';

ws=
new WebSocket(
`${proto}://${location.host}/ws/terminal`
);

ws.onopen=
()=>{

$('termState')
.textContent=
'connected';

$('statusDot')
.style.background=
'var(--accent)';

term.focus();

fitTerminal();

};

ws.onmessage=
e=>
term.write(
e.data
);

ws.onclose=
()=>{

$('termState')
.textContent=
'reconnecting';

$('statusDot')
.style.background=
'var(--danger)';

clearTimeout(
reconnectTimer
);

reconnectTimer=
setTimeout(
connectTerminal,
1200
);

};

ws.onerror=
()=>{};

}

term.onData(
data=>
sendWS(
{
type:'input',
data
}
)
);

term.onResize(
size=>
sendWS(
{
type:'resize',
cols:size.cols,
rows:size.rows
}
)
);

function fitTerminal(){

try{

fitAddon.fit();

sendWS(
{
type:'resize',
cols:term.cols,
rows:term.rows
}
);

}catch(e){}

}

window.addEventListener(
'resize',
fitTerminal
);

async function init(){

try{

await loadStyle();

await loadRoots();

const state=
await api(
'/api/state'
);

if(state.lastFile){

try{

await openFile(
state.lastFile
);

}catch(e){}

}

}catch(e){

toast(
e.message
);

}

connectTerminal();

setTimeout(
fitTerminal,
200
);

}

init();

</script>

</body>
</html>'''


ensure_data_files()


if __name__ == "__main__":
    print(APP_NAME)
    print(f"Home: {HOME}")
    print(f"Shared: {SHARED}")
    print(f"Data: {DATA_ROOT}")
    print(f"Open: http://{HOST}:{PORT}")

    app.run(
        host=HOST,
        port=PORT,
        threaded=True,
        debug=False
    )
