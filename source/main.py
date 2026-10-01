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

APP_NAME = "VStermu-x"
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
IGNORED_FILE_NAMES = {"vstermu-installer.py"}
ENV_NOTICE = "Sorry, but for your protection, this feature is disabled by default. Go to Termux, and in the command tab created when you ran it, there will be a command line \">>>\". Type \".env enable\"."

app = Flask(__name__)
app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25}
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


def atomic_json_write(path, value):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".vstemu-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
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


def default_state():
    return {"openFiles": [], "lastFile": None, "envEnabled": False}


def get_state():
    state = load_json(STATE_FILE, default_state())
    if not isinstance(state, dict):
        state = default_state()

    if not isinstance(state.get("openFiles"), list):
        state["openFiles"] = []

    if "lastFile" not in state:
        state["lastFile"] = None

    state["envEnabled"] = bool(state.get("envEnabled", False))
    return state


def set_env_enabled(enabled):
    state = get_state()
    state["envEnabled"] = bool(enabled)
    atomic_json_write(STATE_FILE, state)
    return state["envEnabled"]


def env_enabled():
    return get_state()["envEnabled"]


def is_env_file(path):
    name = os.path.basename(os.path.realpath(path)).lower()
    return name == ".env" or name.startswith(".env.")


def protect_env_content(content):
    result = []

    for line in content.splitlines(keepends=True):
        newline = ""
        raw = line

        if raw.endswith("\r\n"):
            raw = raw[:-2]
            newline = "\r\n"
        elif raw.endswith("\n") or raw.endswith("\r"):
            newline = raw[-1]
            raw = raw[:-1]

        if not raw.strip() or raw.lstrip().startswith("#") or "=" not in raw:
            result.append(raw + newline)
            continue

        key, _, _ = raw.partition("=")
        result.append(key + "=[value hidden]" + newline)

    return "".join(result)


def ensure_data_files():
    os.makedirs(SCRIPTS_SAVE, exist_ok=True)
    os.makedirs(STYLE_DIR, exist_ok=True)

    if not os.path.exists(STYLE_FILE):
        atomic_json_write(STYLE_FILE, DEFAULT_STYLE)

    if not os.path.exists(STATE_FILE):
        atomic_json_write(STATE_FILE, default_state())


def roots():
    result = [{"name": "Termux Home", "path": HOME, "kind": "home"}]

    if os.path.isdir(SHARED):
        result.append(
            {
                "name": "Shared Storage",
                "path": os.path.realpath(SHARED),
                "kind": "shared",
            }
        )

    return result


def allowed(path):
    real = os.path.realpath(path)

    for root in (HOME, os.path.realpath(SHARED)):
        if real == root or real.startswith(root + os.sep):
            return real

    raise PermissionError("Path outside allowed Termux roots")


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
        return "/storage/emulated/0/" + os.path.relpath(real, shared)

    return real


def file_icon(name, directory=False):
    if directory:
        return "fa-solid fa-folder"

    lower = name.lower()

    if lower == ".env" or lower.startswith(".env."):
        return EXTENSIONS["env"]

    ext = lower.rsplit(".", 1)[-1] if "." in lower else ""
    return EXTENSIONS.get(ext, "fa-solid fa-file")


def list_directory(path):
    directory = safe_path(path)

    if not os.path.isdir(directory):
        raise FileNotFoundError(directory)

    entries = []

    with os.scandir(directory) as scan:
        for entry in scan:
            if len(entries) >= MAX_SCAN_ITEMS:
                break

            if not entry.is_dir(follow_symlinks=False) and entry.name in IGNORED_FILE_NAMES:
                continue

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                stat = entry.stat(follow_symlinks=False)

                entries.append(
                    {
                        "name": entry.name,
                        "path": entry.path,
                        "type": "directory" if is_dir else "file",
                        "icon": file_icon(entry.name, is_dir),
                        "size": stat.st_size if not is_dir else 0,
                        "mtime": stat.st_mtime,
                        "hidden": entry.name.startswith("."),
                        "symlink": entry.is_symlink(),
                        "protected": (
                            not is_dir
                            and is_env_file(entry.path)
                            and not env_enabled()
                        ),
                    }
                )
            except (PermissionError, FileNotFoundError, OSError):
                continue

    entries.sort(key=lambda x: (x["type"] != "directory", x["name"].lower()))
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

    if ext in text_ext or os.path.basename(path).startswith("."):
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

    os.makedirs(parent, exist_ok=True)

    fd, temp = tempfile.mkstemp(prefix=".vstemu-write-", dir=parent)

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def parse_lint_error(text, language):
    message = text.strip().splitlines()
    joined = " ".join(x.strip() for x in message if x.strip())

    line = 0
    column = 0

    patterns = [
        r"line (\d+), column (\d+)",
        r"line (\d+).*?column (\d+)",
        r":(\d+):(\d+)",
        r"line (\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            line = max(0, int(match.group(1)) - 1)

            if match.lastindex and match.lastindex >= 2:
                column = max(0, int(match.group(2)) - 1)

            break

    if not joined:
        joined = f"Syntax check failed for {language}"

    return {
        "line": line,
        "column": column,
        "message": joined[:500],
    }


def generic_lint(content):
    errors = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = []
    line = 0

    for index, char in enumerate(content):
        if char in pairs:
            stack.append((char, line, index))

        elif char in pairs.values():
            expected = None

            for opening, closing in pairs.items():
                if closing == char:
                    expected = opening
                    break

            if not stack or stack[-1][0] != expected:
                errors.append(
                    {
                        "line": line,
                        "column": index,
                        "message": f"Unexpected {char}",
                    }
                )
                break

            stack.pop()

        if char == "\n":
            line += 1

    if not errors and stack:
        opening, stack_line, stack_column = stack[-1]

        errors.append(
            {
                "line": stack_line,
                "column": stack_column,
                "message": f"Unclosed {opening}",
            }
        )

    return errors


def lint_code(content, filename):
    suffix = Path(filename).suffix.lower()

    language = {
        ".py": "python",
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".json": "json",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".scss": "css",
        ".sh": "shell",
        ".bash": "shell",
        ".zsh": "shell",
        ".fish": "shell",
        ".php": "php",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".rs": "rust",
        ".go": "go",
        ".sql": "sql",
        ".xml": "xml",
    }.get(suffix, "text")

    if suffix == ".py":
        process = subprocess.run(
            ["python", "-m", "py_compile", "-"],
            input=content,
            text=True,
            capture_output=True,
            timeout=10,
        )

        if process.returncode:
            return [parse_lint_error(process.stderr, language)]

        return []

    if suffix in {".js", ".mjs", ".cjs"}:
        node = shutil.which("node")

        if node:
            process = subprocess.run(
                [node, "--check", "-"],
                input=content,
                text=True,
                capture_output=True,
                timeout=10,
            )

            if process.returncode:
                return [parse_lint_error(process.stderr, language)]

        return []

    if suffix == ".json":
        try:
            json.loads(content)
            return []
        except json.JSONDecodeError as exc:
            return [
                {
                    "line": exc.lineno - 1,
                    "column": exc.colno - 1,
                    "message": exc.msg,
                }
            ]

    return generic_lint(content)


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.get("/api/style")
def get_style():
    style = load_json(STYLE_FILE, DEFAULT_STYLE)

    if not isinstance(style, dict):
        style = DEFAULT_STYLE.copy()

    return jsonify(style)


@app.put("/api/style")
def put_style():
    data = request.get_json(silent=True) or {}
    style = load_json(STYLE_FILE, DEFAULT_STYLE)

    if not isinstance(style, dict):
        style = DEFAULT_STYLE.copy()

    for key in DEFAULT_STYLE:
        if key in data:
            style[key] = data[key]

    atomic_json_write(STYLE_FILE, style)
    return jsonify(style)


@app.get("/api/env/status")
def env_status():
    return jsonify({"enabled": env_enabled()})


@app.post("/api/env/set")
def env_set():
    data = request.get_json(silent=True) or {}
    return jsonify({"enabled": set_env_enabled(bool(data.get("enabled")))})


@app.get("/api/roots")
def get_roots():
    return jsonify({"roots": roots()})


@app.get("/api/tree")
def get_tree():
    path = request.args.get("path", HOME)
    return jsonify(
        {
            "path": safe_path(path),
            "entries": list_directory(path),
        }
    )


@app.post("/api/file/read")
def read_file():
    data = request.get_json(silent=True) or {}
    path = safe_path(data.get("path"))

    if os.path.basename(path) in IGNORED_FILE_NAMES:
        raise PermissionError("This file is unavailable")

    if is_env_file(path) and not env_enabled():
        raise PermissionError(ENV_NOTICE)

    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    if os.path.getsize(path) > MAX_FILE_SIZE:
        raise ValueError("File is too large")

    if not is_probably_text(path):
        raise ValueError("Binary files cannot be opened")

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        content = handle.read()

    return jsonify(
        {
            "path": path,
            "name": os.path.basename(path),
            "content": content,
        }
    )


@app.post("/api/file/write")
def write_file():
    data = request.get_json(silent=True) or {}
    path = safe_path(data.get("path"))

    if os.path.basename(path) in IGNORED_FILE_NAMES:
        raise PermissionError("This file is unavailable")

    if is_env_file(path) and not env_enabled():
        raise PermissionError(ENV_NOTICE)

    content = data.get("content", "")

    if not isinstance(content, str):
        raise ValueError("Invalid content")

    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        raise ValueError("File is too large")

    atomic_write(path, content.encode("utf-8"))

    return jsonify(
        {
            "ok": True,
            "path": path,
        }
    )


@app.post("/api/file/create")
def create_file():
    data = request.get_json(silent=True) or {}
    parent = safe_path(data.get("parent"))
    name = str(data.get("name", "")).strip()

    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Invalid file name")

    path = safe_path(os.path.join(parent, name))

    if os.path.exists(path):
        raise FileExistsError(path)

    if name in IGNORED_FILE_NAMES:
        raise PermissionError("This file name is reserved")

    atomic_write(path, b"")

    return jsonify(
        {
            "ok": True,
            "path": path,
        }
    )


@app.post("/api/folder/create")
def create_folder():
    data = request.get_json(silent=True) or {}
    parent = safe_path(data.get("parent"))
    name = str(data.get("name", "")).strip()

    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Invalid folder name")

    path = safe_path(os.path.join(parent, name))

    if os.path.exists(path):
        raise FileExistsError(path)

    os.makedirs(path)

    return jsonify(
        {
            "ok": True,
            "path": path,
        }
    )


@app.post("/api/file/rename")
def rename_file():
    data = request.get_json(silent=True) or {}
    source = safe_path(data.get("path"))
    name = str(data.get("name", "")).strip()

    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Invalid name")

    if os.path.basename(source) in IGNORED_FILE_NAMES:
        raise PermissionError("This file is unavailable")

    if is_env_file(source) and not env_enabled():
        raise PermissionError(ENV_NOTICE)

    destination = safe_path(
        os.path.join(os.path.dirname(source), name)
    )

    if destination != source and os.path.exists(destination):
        raise FileExistsError(destination)

    os.rename(source, destination)

    return jsonify(
        {
            "ok": True,
            "path": destination,
        }
    )


@app.post("/api/file/delete")
def delete_file():
    data = request.get_json(silent=True) or {}
    path = safe_path(data.get("path"))

    if os.path.basename(path) in IGNORED_FILE_NAMES:
        raise PermissionError("This file is unavailable")

    if is_env_file(path) and not env_enabled():
        raise PermissionError(ENV_NOTICE)

    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.isfile(path):
        os.remove(path)
    else:
        raise FileNotFoundError(path)

    return jsonify({"ok": True})


@app.post("/api/lint")
def api_lint():
    data = request.get_json(silent=True) or {}

    return jsonify(
        {
            "errors": lint_code(
                data.get("content", ""),
                data.get("filename", ""),
            )
        }
    )


@app.get("/api/state")
def api_state():
    return jsonify(get_state())


@app.put("/api/state")
def put_state():
    data = request.get_json(silent=True) or {}
    state = get_state()

    if isinstance(data.get("openFiles"), list):
        state["openFiles"] = [
            x for x in data["openFiles"] if isinstance(x, str)
        ][:20]

    if "lastFile" in data:
        state["lastFile"] = data.get("lastFile")

    atomic_json_write(STATE_FILE, state)

    return jsonify(state)


@app.errorhandler(Exception)
def handle_error(error):
    code = 400

    if isinstance(error, PermissionError):
        code = 403
    elif isinstance(error, FileNotFoundError):
        code = 404
    elif isinstance(error, FileExistsError):
        code = 409
    elif isinstance(error, ValueError):
        code = 400

    return jsonify({"error": str(error)}), code


def shell_quote(value):
    return "'" + value.replace("'", "'\\''") + "'"


def spawn_shell(cwd):
    env = os.environ.copy()
    shell = os.environ.get("SHELL")

    if shell and os.path.exists(shell):
        command = [shell, "-l"]
    else:
        command = ["/system/bin/sh"]

    master, slave = os.openpty()

    process = subprocess.Popen(
        command,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=cwd,
        env=env,
        start_new_session=True,
        close_fds=True,
    )

    os.close(slave)

    return master, process


class TerminalSession:
    def __init__(self, cwd):
        self.cwd = cwd
        self.master, self.process = spawn_shell(cwd)

    def write(self, data):
        if not data:
            return

        try:
            os.write(
                self.master,
                data.encode("utf-8", errors="replace"),
            )
        except OSError:
            pass

    def resize(self, cols, rows):
        try:
            cols = max(1, min(500, int(cols)))
            rows = max(1, min(200, int(rows)))
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(
                self.master,
                termios.TIOCSWINSZ,
                winsize,
            )
        except Exception:
            pass

    def read_available(self):
        output = []

        while True:
            try:
                readable, _, _ = select.select(
                    [self.master],
                    [],
                    [],
                    0,
                )
            except Exception:
                break

            if not readable:
                break

            try:
                data = os.read(self.master, 65536)
            except OSError:
                break

            if not data:
                break

            output.append(
                data.decode(
                    "utf-8",
                    errors="replace",
                )
            )

        return "".join(output)

    def close(self):
        try:
            if self.process.poll() is None:
                os.killpg(
                    self.process.pid,
                    signal.SIGTERM,
                )
        except Exception:
            pass

        try:
            os.close(self.master)
        except Exception:
            pass


@sock.route("/ws/terminal")
def ws_terminal(ws):
    cwd = HOME
    session = None

    try:
        session = TerminalSession(cwd)
        session.resize(100, 30)

        while True:
            if session.process.poll() is not None:
                output = session.read_available()

                if output:
                    try:
                        ws.send(output)
                    except Exception:
                        pass

                break

            try:
                readable, _, _ = select.select(
                    [session.master],
                    [],
                    [],
                    0.08,
                )
            except Exception:
                break

            if readable:
                output = session.read_available()

                if output:
                    try:
                        ws.send(output)
                    except Exception:
                        break

            try:
                message = ws.receive(timeout=0)
            except Exception:
                message = None

            if not message:
                continue

            try:
                packet = json.loads(message)
            except Exception:
                packet = {
                    "type": "input",
                    "data": message,
                }

            kind = packet.get("type")

            if kind == "input":
                session.write(
                    packet.get("data", "")
                )

            elif kind == "resize":
                session.resize(
                    packet.get("cols", 100),
                    packet.get("rows", 30),
                )

            elif kind == "cwd":
                try:
                    path = safe_path(
                        packet.get("path", HOME)
                    )

                    if os.path.isdir(path):
                        session.write(
                            "cd -- "
                            + shell_quote(path)
                            + "\n"
                        )
                except Exception:
                    pass

    except Exception:
        pass

    finally:
        if session:
            session.close()


PAGE = r'''
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#090b10">
<title>VStermu-x</title>
<style>
* {
    box-sizing: border-box;
}

html,
body {
    width: 100%;
    height: 100%;
    margin: 0;
    background: #090b10;
    color: #e8edf6;
    font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    overflow: hidden;
}

body {
    position: relative;
}

button,
input,
textarea {
    font: inherit;
}

button {
    border: 0;
}

#loadingScreen {
    position: fixed;
    inset: 0;
    z-index: 99999;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #090b10;
    transition: opacity .35s ease, visibility .35s ease;
}

#loadingScreen.done {
    opacity: 0;
    visibility: hidden;
    pointer-events: none;
}

.loadingInner {
    width: min(90vw, 360px);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 16px;
}

.loadingTitle {
    font-size: 25px;
    font-weight: 700;
    letter-spacing: -.5px;
}

.loadingWelcome {
    color: #8e98aa;
    font-size: 14px;
}

.loaderDots {
    display: flex;
    gap: 7px;
    align-items: center;
    justify-content: center;
    min-height: 20px;
}

.loaderDot {
    width: 7px;
    height: 7px;
    border-radius: 2px;
    background: #8ca2ff;
    animation: loaderStretch .9s infinite ease-in-out;
}

.loaderDot:nth-child(2) {
    animation-delay: .12s;
}

.loaderDot:nth-child(3) {
    animation-delay: .24s;
}

@keyframes loaderStretch {
    0%,
    100% {
        transform: scaleY(1);
        opacity: .45;
    }

    50% {
        transform: scaleY(2.7);
        opacity: 1;
    }
}

#app {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
}

.topbar {
    height: 54px;
    flex: 0 0 54px;
    border-bottom: 1px solid #1b202b;
    background: #0c0f15;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 12px;
    gap: 10px;
}

.brand {
    display: flex;
    align-items: center;
    gap: 9px;
    min-width: 0;
}

.brandMark {
    width: 27px;
    height: 27px;
    border-radius: 8px;
    background: #151b27;
    border: 1px solid #252e3e;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #9bb0ff;
    font-size: 13px;
    flex: 0 0 auto;
}

.brandText {
    font-size: 15px;
    font-weight: 700;
    white-space: nowrap;
}

.topActions {
    display: flex;
    align-items: center;
    gap: 6px;
}

.actionButton {
    min-height: 34px;
    padding: 0 11px;
    border-radius: 8px;
    color: #dce3ef;
    background: #121720;
    border: 1px solid #222b3a;
    cursor: pointer;
}

.actionButton:hover {
    background: #181f2b;
}

.actionButton.primary {
    background: #1c2944;
    border-color: #2f4670;
    color: #cfdaff;
}

.workspace {
    min-height: 0;
    flex: 1;
    display: flex;
    overflow: hidden;
}

.sidebar {
    width: 280px;
    min-width: 210px;
    max-width: 50vw;
    border-right: 1px solid #1b202b;
    background: #0b0e13;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.sidebarHeader {
    padding: 12px;
    border-bottom: 1px solid #171c25;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 7px;
}

.sidebarTitle {
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .9px;
    color: #8b94a5;
}

.sidebarTools {
    display: flex;
    gap: 5px;
}

.miniButton {
    width: 29px;
    height: 29px;
    border-radius: 7px;
    border: 1px solid #202733;
    background: #12161e;
    color: #aeb8ca;
    cursor: pointer;
}

.miniButton:hover {
    background: #191f2a;
}

.pathBar {
    margin: 9px 10px;
    min-height: 32px;
    padding: 7px 9px;
    border: 1px solid #1d2531;
    border-radius: 7px;
    background: #0d1118;
    color: #939eaf;
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.tree {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 3px 7px 12px;
}

.treeRow {
    width: 100%;
    min-height: 34px;
    border-radius: 7px;
    padding: 6px 8px;
    color: #bec7d5;
    background: transparent;
    display: flex;
    align-items: center;
    gap: 8px;
    text-align: left;
    cursor: pointer;
}

.treeRow:hover {
    background: #121720;
}

.treeRow.active {
    background: #182132;
    color: #e3eaff;
}

.treeIcon {
    width: 17px;
    flex: 0 0 17px;
    text-align: center;
    opacity: .85;
}

.treeName {
    min-width: 0;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
}

.treeArrow {
    width: 15px;
    text-align: center;
    color: #727c8d;
    font-size: 10px;
}

.protected {
    opacity: .55;
}

.main {
    min-width: 0;
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.tabs {
    height: 40px;
    flex: 0 0 40px;
    display: flex;
    align-items: stretch;
    border-bottom: 1px solid #1a202a;
    background: #0c1016;
    overflow-x: auto;
    overflow-y: hidden;
}

.tab {
    min-width: 130px;
    max-width: 220px;
    display: flex;
    align-items: center;
    gap: 8px;
    border-right: 1px solid #171c25;
    padding: 0 10px;
    color: #8d97a8;
    cursor: pointer;
    white-space: nowrap;
}

.tab.active {
    color: #e0e7f2;
    background: #11161e;
}

.tabName {
    min-width: 0;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
}

.tabClose {
    width: 20px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 5px;
    color: #7e8797;
    background: transparent;
}

.tabClose:hover {
    background: #1b222d;
    color: #d3dae5;
}

.editorArea {
    min-height: 0;
    flex: 1;
    position: relative;
    display: flex;
    flex-direction: column;
}

.emptyState {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 25px;
    text-align: center;
    gap: 8px;
}

.emptyTitle {
    color: #dbe2ed;
    font-size: 18px;
    font-weight: 650;
}

.emptyText {
    color: #727d90;
    max-width: 360px;
    font-size: 13px;
    line-height: 1.5;
}

#editor {
    width: 100%;
    height: 100%;
    flex: 1;
    border: 0;
    outline: 0;
    resize: none;
    background: #0b0f15;
    color: #dfe7f3;
    padding: 18px 18px 22px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 14px;
    line-height: 1.65;
    tab-size: 4;
    white-space: pre;
    overflow: auto;
    display: none;
}

.editorBar {
    min-height: 38px;
    border-top: 1px solid #1b2029;
    background: #0c1016;
    display: none;
    align-items: center;
    justify-content: space-between;
    padding: 5px 9px;
    gap: 8px;
}

.fileStatus {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: #778294;
    font-size: 11px;
}

.statusOk {
    color: #83b795;
}

.statusError {
    color: #d28a8a;
}

.bottom {
    height: 280px;
    min-height: 150px;
    max-height: 60vh;
    border-top: 1px solid #1b202b;
    background: #080b10;
    display: flex;
    flex-direction: column;
}

.bottomHeader {
    height: 38px;
    flex: 0 0 38px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 10px;
    border-bottom: 1px solid #171c25;
}

.bottomTitle {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #9aa5b6;
    font-size: 12px;
    font-weight: 700;
}

.terminalConnection {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #ad6c6c;
}

.terminalConnection.connected {
    background: #72aa82;
}

.terminal {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 10px 12px;
    color: #d4dbe6;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 13px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
}

.terminalInput {
    height: 35px;
    flex: 0 0 35px;
    border: 0;
    border-top: 1px solid #171c25;
    outline: none;
    background: #0a0e14;
    color: #d7dfeb;
    padding: 0 12px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 13px;
}

.liveCodePanel {
    position: absolute;
    left: 12px;
    right: 12px;
    bottom: 12px;
    top: 12px;
    z-index: 20;
    border: 1px solid #273141;
    border-radius: 10px;
    overflow: hidden;
    background: #090c11;
    display: none;
    flex-direction: column;
}

.liveCodePanel.visible {
    display: flex;
}

.liveCodeHeader {
    height: 38px;
    flex: 0 0 38px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 9px 0 12px;
    border-bottom: 1px solid #1d2530;
}

.liveCodeTitle {
    color: #cdd6e3;
    font-size: 12px;
    font-weight: 700;
}

.liveCodeClose {
    width: 27px;
    height: 27px;
    border-radius: 6px;
    background: #161c25;
    color: #aab4c4;
    cursor: pointer;
}

#liveCodeFrame {
    border: 0;
    width: 100%;
    flex: 1;
    min-height: 0;
    background: white;
}

.toastContainer {
    position: fixed;
    right: 12px;
    bottom: 12px;
    z-index: 100000;
    display: flex;
    flex-direction: column;
    gap: 7px;
    pointer-events: none;
}

.toast {
    max-width: min(420px, calc(100vw - 24px));
    border: 1px solid #252e3c;
    background: #11161e;
    color: #dce4f0;
    padding: 10px 12px;
    border-radius: 8px;
    box-shadow: 0 14px 35px rgba(0,0,0,.35);
    font-size: 12px;
    pointer-events: auto;
    animation: toastIn .2s ease;
}

@keyframes toastIn {
    from {
        opacity: 0;
        transform: translateY(5px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.modalBackdrop {
    position: fixed;
    inset: 0;
    z-index: 9000;
    background: rgba(0,0,0,.55);
    display: none;
    align-items: center;
    justify-content: center;
    padding: 18px;
}

.modalBackdrop.visible {
    display: flex;
}

.modal {
    width: min(92vw, 400px);
    border: 1px solid #252d3a;
    border-radius: 12px;
    background: #10141b;
    box-shadow: 0 24px 70px rgba(0,0,0,.5);
    overflow: hidden;
}

.modalHeader {
    padding: 13px 15px;
    border-bottom: 1px solid #1d2430;
    color: #e0e6ef;
    font-size: 14px;
    font-weight: 700;
}

.modalBody {
    padding: 15px;
}

.modalInput {
    width: 100%;
    height: 38px;
    border-radius: 8px;
    border: 1px solid #283242;
    outline: none;
    background: #0a0e13;
    color: #e1e7ef;
    padding: 0 10px;
}

.modalFooter {
    padding: 12px 15px;
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    border-top: 1px solid #1d2430;
}

.mobileToggle {
    display: none;
}

@media (max-width: 800px) {
    .sidebar {
        width: 235px;
    }

    .bottom {
        height: 230px;
    }

    .mobileToggle {
        display: flex;
    }
}

@media (max-width: 620px) {
    .sidebar {
        position: absolute;
        top: 54px;
        bottom: 0;
        left: 0;
        z-index: 100;
        width: min(82vw, 310px);
        transform: translateX(-102%);
        transition: transform .2s ease;
        box-shadow: 18px 0 40px rgba(0,0,0,.25);
    }

    .sidebar.mobileVisible {
        transform: translateX(0);
    }

    .topActions .hideMobile {
        display: none;
    }

    .bottom {
        height: 220px;
    }

    .tab {
        min-width: 120px;
    }

    #editor {
        padding: 14px;
        font-size: 13px;
    }
}
</style>
</head>
<body>

<div id="loadingScreen">
    <div class="loadingInner">
        <div class="loadingTitle">VStermu-x</div>
        <div class="loadingWelcome">Welcome!</div>
        <div class="loaderDots">
            <span class="loaderDot"></span>
            <span class="loaderDot"></span>
            <span class="loaderDot"></span>
        </div>
    </div>
</div>

<div id="app">
    <header class="topbar">
        <div class="brand">
            <button class="actionButton mobileToggle" id="sidebarToggle" type="button">☰</button>
            <div class="brandMark">&gt;_</div>
            <div class="brandText">VStermu-x</div>
        </div>

        <div class="topActions">
            <button class="actionButton hideMobile" id="liveCodeButton" type="button">Live Code</button>
            <button class="actionButton primary" id="saveButton" type="button">Save</button>
        </div>
    </header>

    <div class="workspace">
        <aside class="sidebar" id="sidebar">
            <div class="sidebarHeader">
                <div class="sidebarTitle">Explorer</div>
                <div class="sidebarTools">
                    <button class="miniButton" id="refreshButton" type="button">↻</button>
                    <button class="miniButton" id="addFileButton" type="button">+</button>
                </div>
            </div>

            <div class="pathBar" id="pathBar">Loading filesystem...</div>

            <div class="tree" id="tree">
                <div class="treeRow">
                    <div class="treeIcon">•</div>
                    <div class="treeName">Loading filesystem...</div>
                </div>
            </div>
        </aside>

        <main class="main">
            <div class="tabs" id="tabs"></div>

            <div class="editorArea">
                <div class="emptyState" id="emptyState">
                    <div class="emptyTitle">No file open</div>
                    <div class="emptyText">Select a file to edit. Files are loaded only when opened.</div>
                </div>

                <textarea id="editor" spellcheck="false" autocapitalize="off" autocomplete="off"></textarea>

                <div class="editorBar" id="editorBar">
                    <div class="fileStatus" id="fileStatus">Select a file to edit.</div>
                    <button class="miniButton" id="lintButton" type="button">✓</button>
                </div>

                <div class="liveCodePanel" id="liveCodePanel">
                    <div class="liveCodeHeader">
                        <div class="liveCodeTitle">Live Code</div>
                        <button class="liveCodeClose" id="liveCodeClose" type="button">×</button>
                    </div>
                    <iframe id="liveCodeFrame" sandbox="allow-scripts allow-forms allow-modals"></iframe>
                </div>
            </div>

            <section class="bottom">
                <div class="bottomHeader">
                    <div class="bottomTitle">
                        <span class="terminalConnection" id="terminalConnection"></span>
                        Termux terminal
                    </div>
                    <button class="miniButton" id="clearTerminalButton" type="button">⌫</button>
                </div>

                <div class="terminal" id="terminal">Connecting...</div>
                <input class="terminalInput" id="terminalInput" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Type a command...">
            </section>
        </main>
    </div>
</div>

<div class="toastContainer" id="toastContainer"></div>

<div class="modalBackdrop" id="modalBackdrop">
    <div class="modal">
        <div class="modalHeader" id="modalTitle">Action</div>
        <div class="modalBody">
            <input class="modalInput" id="modalInput" autocomplete="off">
        </div>
        <div class="modalFooter">
            <button class="actionButton" id="modalCancel" type="button">Cancel</button>
            <button class="actionButton primary" id="modalConfirm" type="button">Confirm</button>
        </div>
    </div>
</div>

<script>
(function() {
    "use strict";

    let loadingFinished = false;
    let loadingTimer = null;

    const state = {
        cwd: null,
        entries: [],
        openFiles: new Map(),
        activePath: null,
        terminalSocket: null,
        terminalConnected: false,
        lintTimer: null,
        modalResolver: null,
        liveCodeEnabled: false
    };

    const $ = function(id) {
        return document.getElementById(id);
    };

    const loadingScreen = $("loadingScreen");

    function finishLoading() {
        if (loadingFinished) {
            return;
        }

        loadingFinished = true;

        if (loadingTimer) {
            clearTimeout(loadingTimer);
            loadingTimer = null;
        }

        if (loadingScreen) {
            loadingScreen.classList.add("done");

            window.setTimeout(function() {
                if (loadingScreen && loadingScreen.parentNode) {
                    loadingScreen.parentNode.removeChild(loadingScreen);
                }
            }, 450);
        }
    }

    loadingTimer = window.setTimeout(function() {
        finishLoading();
    }, 10000);

    async function api(url, options, timeout) {
        const controller = new AbortController();
        const requestTimeout = timeout || 8000;
        const timer = window.setTimeout(function() {
            controller.abort();
        }, requestTimeout);

        try {
            const response = await fetch(url, {
                ...(options || {}),
                signal: controller.signal
            });

            let payload = null;

            try {
                payload = await response.json();
            } catch (error) {
                payload = null;
            }

            if (!response.ok) {
                const message = payload && payload.error
                    ? payload.error
                    : "Request failed with status " + response.status;

                throw new Error(message);
            }

            return payload;
        } finally {
            clearTimeout(timer);
        }
    }

    function showToast(message) {
        const container = $("toastContainer");

        if (!container) {
            return;
        }

        const toast = document.createElement("div");
        toast.className = "toast";
        toast.textContent = String(message);

        container.appendChild(toast);

        window.setTimeout(function() {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 3200);
    }

    function pathLabel(path) {
        if (!path) {
            return "";
        }

        if (state.cwd === path) {
            return path === "/" ? "/" : path;
        }

        return path;
    }

    function iconForEntry(entry) {
        if (entry.type === "directory") {
            return "▰";
        }

        const name = String(entry.name || "").toLowerCase();

        if (name.endsWith(".py")) {
            return "Py";
        }

        if (name.endsWith(".js") || name.endsWith(".ts")) {
            return "JS";
        }

        if (name.endsWith(".html") || name.endsWith(".htm")) {
            return "◇";
        }

        if (name.endsWith(".css")) {
            return "C";
        }

        if (name.endsWith(".json")) {
            return "{}";
        }

        if (name.endsWith(".md")) {
            return "M";
        }

        if (name.endsWith(".sh")) {
            return "$";
        }

        if (name.endsWith(".svg")) {
            return "S";
        }

        if (name === ".env" || name.startsWith(".env.")) {
            return "•";
        }

        return "·";
    }

    function renderTree() {
        const tree = $("tree");
        tree.innerHTML = "";

        if (!state.cwd) {
            const row = document.createElement("div");
            row.className = "treeRow";
            row.innerHTML = '<div class="treeIcon">•</div><div class="treeName">Loading filesystem...</div>';
            tree.appendChild(row);
            return;
        }

        for (const entry of state.entries) {
            const row = document.createElement("button");
            row.type = "button";
            row.className = "treeRow";

            if (entry.path === state.activePath) {
                row.classList.add("active");
            }

            if (entry.protected) {
                row.classList.add("protected");
            }

            const arrow = entry.type === "directory" ? "›" : "";

            row.innerHTML =
                '<div class="treeArrow">' + arrow + '</div>' +
                '<div class="treeIcon">' + escapeHtml(iconForEntry(entry)) + '</div>' +
                '<div class="treeName"></div>';

            row.querySelector(".treeName").textContent = entry.name;

            row.addEventListener("click", function() {
                if (entry.type === "directory") {
                    loadDirectory(entry.path);
                } else {
                    openFile(entry.path);
                }
            });

            tree.appendChild(row);
        }

        if (!state.entries.length) {
            const empty = document.createElement("div");
            empty.className = "treeRow";
            empty.innerHTML = '<div class="treeArrow"></div><div class="treeIcon">·</div><div class="treeName">Empty directory</div>';
            tree.appendChild(empty);
        }
    }

    function escapeHtml(value) {
        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    async function loadDirectory(path, silent) {
        try {
            const data = await api(
                "/api/tree?path=" + encodeURIComponent(path),
                {},
                7000
            );

            state.cwd = data.path;
            state.entries = Array.isArray(data.entries)
                ? data.entries
                : [];

            $("pathBar").textContent = relPath(data.path);
            renderTree();

            if (!silent) {
                showToast("Directory opened");
            }

            return true;
        } catch (error) {
            $("pathBar").textContent = "Unable to load filesystem";
            showToast(error.message || "Unable to load directory");
            return false;
        }
    }

    function relPath(path) {
        if (!path) {
            return "";
        }

        return path
            .replace(/^\/data\/data\/com\.termux\/files\/home/, "~")
            .replace(/^\/data\/data\/com\.termux\/files\/home\//, "~/");
    }

    function setEditorVisible(visible) {
        $("emptyState").style.display = visible ? "none" : "flex";
        $("editor").style.display = visible ? "block" : "none";
        $("editorBar").style.display = visible ? "flex" : "none";
    }

    function renderTabs() {
        const tabs = $("tabs");
        tabs.innerHTML = "";

        for (const [path, file] of state.openFiles.entries()) {
            const tab = document.createElement("div");
            tab.className = "tab";

            if (path === state.activePath) {
                tab.classList.add("active");
            }

            const name = document.createElement("div");
            name.className = "tabName";
            name.textContent = file.name;

            const close = document.createElement("button");
            close.type = "button";
            close.className = "tabClose";
            close.textContent = "×";

            close.addEventListener("click", function(event) {
                event.stopPropagation();
                closeFile(path);
            });

            tab.appendChild(name);
            tab.appendChild(close);

            tab.addEventListener("click", function() {
                activateFile(path);
            });

            tabs.appendChild(tab);
        }
    }

    function activateFile(path) {
        const file = state.openFiles.get(path);

        if (!file) {
            return;
        }

        state.activePath = path;
        $("editor").value = file.content;
        $("fileStatus").textContent = relPath(path);
        $("fileStatus").className = "fileStatus";

        setEditorVisible(true);
        renderTabs();
        renderTree();

        saveState();
        scheduleLint();
        updateLiveCode();
    }

    async function openFile(path) {
        const existing = state.openFiles.get(path);

        if (existing) {
            activateFile(path);
            closeMobileSidebar();
            return;
        }

        try {
            const data = await api(
                "/api/file/read",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        path: path
                    })
                },
                9000
            );

            state.openFiles.set(path, {
                path: data.path,
                name: data.name,
                content: data.content,
                dirty: false
            });

            activateFile(path);
            closeMobileSidebar();
        } catch (error) {
            showToast(error.message || "Unable to open file");
        }
    }

    function closeFile(path) {
        state.openFiles.delete(path);

        if (state.activePath === path) {
            const next = Array.from(state.openFiles.keys()).pop();

            if (next) {
                activateFile(next);
            } else {
                state.activePath = null;
                $("editor").value = "";
                setEditorVisible(false);
                renderTabs();
                renderTree();
                $("fileStatus").textContent = "Select a file to edit.";
            }
        } else {
            renderTabs();
            renderTree();
        }

        saveState();
    }

    async function saveCurrent() {
        if (!state.activePath) {
            showToast("No file is open");
            return;
        }

        const file = state.openFiles.get(state.activePath);

        if (!file) {
            return;
        }

        file.content = $("editor").value;

        try {
            await api(
                "/api/file/write",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        path: state.activePath,
                        content: file.content
                    })
                },
                10000
            );

            file.dirty = false;
            $("fileStatus").textContent = relPath(state.activePath) + "  •  Saved";
            $("fileStatus").className = "fileStatus statusOk";

            renderTabs();
            saveState();
            scheduleLint();
            updateLiveCode();

            showToast("File saved");
        } catch (error) {
            $("fileStatus").textContent = error.message || "Save failed";
            $("fileStatus").className = "fileStatus statusError";
            showToast(error.message || "Save failed");
        }
    }

    async function createFile() {
        const name = await promptModal(
            "Add file",
            "example.py"
        );

        if (name === null) {
            return;
        }

        const cleanName = name.trim();

        if (!cleanName) {
            return;
        }

        try {
            const data = await api(
                "/api/file/create",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        parent: state.cwd,
                        name: cleanName
                    })
                },
                8000
            );

            await loadDirectory(state.cwd, true);
            await openFile(data.path);
            showToast("File created");
        } catch (error) {
            showToast(error.message || "Unable to create file");
        }
    }

    async function createFolder() {
        const name = await promptModal(
            "Add folder",
            "folder-name"
        );

        if (name === null) {
            return;
        }

        const cleanName = name.trim();

        if (!cleanName) {
            return;
        }

        try {
            await api(
                "/api/folder/create",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        parent: state.cwd,
                        name: cleanName
                    })
                },
                8000
            );

            await loadDirectory(state.cwd, true);
            showToast("Folder created");
        } catch (error) {
            showToast(error.message || "Unable to create folder");
        }
    }

    async function renameActive() {
        if (!state.activePath) {
            showToast("No file is open");
            return;
        }

        const current = state.openFiles.get(state.activePath);
        const name = await promptModal(
            "Rename",
            current ? current.name : ""
        );

        if (name === null) {
            return;
        }

        const cleanName = name.trim();

        if (!cleanName) {
            return;
        }

        try {
            const data = await api(
                "/api/file/rename",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        path: state.activePath,
                        name: cleanName
                    })
                },
                8000
            );

            const file = state.openFiles.get(state.activePath);

            if (file) {
                file.name = cleanName;
                file.path = data.path;
            }

            state.openFiles.set(data.path, file);
            state.openFiles.delete(state.activePath);
            state.activePath = data.path;

            await loadDirectory(state.cwd, true);
            activateFile(data.path);

            showToast("Renamed");
        } catch (error) {
            showToast(error.message || "Unable to rename");
        }
    }

    async function deleteActive() {
        if (!state.activePath) {
            showToast("No file is open");
            return;
        }

        const file = state.openFiles.get(state.activePath);
        const accepted = window.confirm(
            "Delete " + (file ? file.name : state.activePath) + "?"
        );

        if (!accepted) {
            return;
        }

        try {
            await api(
                "/api/file/delete",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        path: state.activePath
                    })
                },
                8000
            );

            state.openFiles.delete(state.activePath);
            state.activePath = null;
            $("editor").value = "";
            setEditorVisible(false);
            renderTabs();

            await loadDirectory(state.cwd, true);
            saveState();

            showToast("Deleted");
        } catch (error) {
            showToast(error.message || "Unable to delete");
        }
    }

    function promptModal(title, placeholder) {
        return new Promise(function(resolve) {
            state.modalResolver = resolve;

            $("modalTitle").textContent = title;
            $("modalInput").value = "";
            $("modalInput").placeholder = placeholder || "";
            $("modalBackdrop").classList.add("visible");

            window.setTimeout(function() {
                $("modalInput").focus();
            }, 40);
        });
    }

    function closeModal(value) {
        $("modalBackdrop").classList.remove("visible");

        if (state.modalResolver) {
            const resolver = state.modalResolver;
            state.modalResolver = null;
            resolver(value);
        }
    }

    function scheduleLint() {
        if (state.lintTimer) {
            clearTimeout(state.lintTimer);
        }

        state.lintTimer = window.setTimeout(function() {
            lintCurrent();
        }, 550);
    }

    async function lintCurrent() {
        if (!state.activePath) {
            return;
        }

        const content = $("editor").value;
        const filename = state.activePath.split("/").pop();

        try {
            const result = await api(
                "/api/lint",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        filename: filename,
                        content: content
                    })
                },
                11000
            );

            const errors = Array.isArray(result.errors)
                ? result.errors
                : [];

            if (!errors.length) {
                $("fileStatus").textContent = relPath(state.activePath) + "  •  No syntax errors";
                $("fileStatus").className = "fileStatus statusOk";
                return;
            }

            const error = errors[0];

            $("fileStatus").textContent =
                "Line " +
                (Number(error.line || 0) + 1) +
                ": " +
                (error.message || "Syntax error");

            $("fileStatus").className = "fileStatus statusError";
        } catch (error) {
            $("fileStatus").textContent = error.message || "Syntax check failed";
            $("fileStatus").className = "fileStatus statusError";
        }
    }

    function detectLanguage(filename) {
        const name = String(filename || "").toLowerCase();

        if (name.endsWith(".html") || name.endsWith(".htm")) {
            return "html";
        }

        if (name.endsWith(".svg")) {
            return "html";
        }

        if (name.endsWith(".css")) {
            return "css";
        }

        if (name.endsWith(".js") || name.endsWith(".mjs") || name.endsWith(".cjs")) {
            return "javascript";
        }

        return "";
    }

    function updateLiveCode() {
        if (!state.liveCodeEnabled || !state.activePath) {
            return;
        }

        const file = state.openFiles.get(state.activePath);

        if (!file) {
            return;
        }

        const language = detectLanguage(file.name);

        if (!language) {
            $("liveCodeFrame").srcdoc =
                "<html><body style=\"font-family:system-ui;padding:24px\">" +
                "<h3>Live Code</h3><p>This preview is available for HTML, CSS and JavaScript files.</p>" +
                "</body></html>";
            return;
        }

        let source = $("editor").value;

        if (language === "html") {
            $("liveCodeFrame").srcdoc = source;
            return;
        }

        if (language === "css") {
            source =
                "<!DOCTYPE html><html><head><style>" +
                source +
                "</style></head><body></body></html>";

            $("liveCodeFrame").srcdoc = source;
            return;
        }

        if (language === "javascript") {
            source =
                "<!DOCTYPE html><html><body><script>" +
                source.replaceAll("</script>", "<\\/script>") +
                "<\/script></body></html>";

            $("liveCodeFrame").srcdoc = source;
        }
    }

    function toggleLiveCode(force) {
        state.liveCodeEnabled =
            typeof force === "boolean"
                ? force
                : !state.liveCodeEnabled;

        $("liveCodePanel").classList.toggle(
            "visible",
            state.liveCodeEnabled
        );

        updateLiveCode();
    }

    function connectTerminal() {
        if (
            state.terminalSocket &&
            (
                state.terminalSocket.readyState === WebSocket.OPEN ||
                state.terminalSocket.readyState === WebSocket.CONNECTING
            )
        ) {
            return;
        }

        const protocol =
            location.protocol === "https:"
                ? "wss:"
                : "ws:";

        const socket = new WebSocket(
            protocol +
            "//" +
            location.host +
            "/ws/terminal"
        );

        state.terminalSocket = socket;

        socket.addEventListener("open", function() {
            state.terminalConnected = true;
            $("terminalConnection").classList.add("connected");
            $("terminal").textContent = "";
        });

        socket.addEventListener("message", function(event) {
            appendTerminal(event.data);
        });

        socket.addEventListener("close", function() {
            state.terminalConnected = false;
            $("terminalConnection").classList.remove("connected");

            window.setTimeout(function() {
                if (!state.terminalConnected) {
                    connectTerminal();
                }
            }, 1500);
        });

        socket.addEventListener("error", function() {
            state.terminalConnected = false;
            $("terminalConnection").classList.remove("connected");
        });
    }

    function appendTerminal(text) {
        const terminal = $("terminal");
        terminal.textContent += String(text);
        terminal.scrollTop = terminal.scrollHeight;
    }

    function sendTerminalInput(value) {
        if (
            !state.terminalSocket ||
            state.terminalSocket.readyState !== WebSocket.OPEN
        ) {
            connectTerminal();
            return;
        }

        state.terminalSocket.send(
            JSON.stringify({
                type: "input",
                data: value
            })
        );
    }

    async function saveState() {
        const paths = Array.from(
            state.openFiles.keys()
        ).slice(0, 20);

        try {
            await api(
                "/api/state",
                {
                    method: "PUT",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        openFiles: paths,
                        lastFile: state.activePath
                    })
                },
                4000
            );
        } catch (error) {
        }
    }

    async function restoreState() {
        try {
            const data = await api(
                "/api/state",
                {},
                5000
            );

            if (
                data &&
                Array.isArray(data.openFiles)
            ) {
                for (
                    const path of data.openFiles.slice(0, 20)
                ) {
                    try {
                        await openFile(path);
                    } catch (error) {
                    }
                }
            }

            if (
                data &&
                data.lastFile &&
                state.openFiles.has(data.lastFile)
            ) {
                activateFile(data.lastFile);
            }
        } catch (error) {
        }
    }

    function closeMobileSidebar() {
        $("sidebar").classList.remove("mobileVisible");
    }

    async function boot() {
        try {
            const roots = await api(
                "/api/roots",
                {},
                5500
            );

            if (
                roots &&
                Array.isArray(roots.roots) &&
                roots.roots.length
            ) {
                await loadDirectory(
                    roots.roots[0].path,
                    true
                );
            } else {
                await loadDirectory(
                    "~",
                    true
                );
            }
        } catch (error) {
            $("pathBar").textContent = "Filesystem unavailable";
            $("tree").innerHTML =
                '<div class="treeRow"><div class="treeArrow"></div><div class="treeIcon">!</div><div class="treeName">Unable to load filesystem</div></div>';
            showToast(error.message || "Unable to load filesystem");
        }

        connectTerminal();

        try {
            const style = await api(
                "/api/style",
                {},
                4000
            );

            if (style) {
                applyStyle(style);
            }
        } catch (error) {
        }

        await restoreState();
    }

    function applyStyle(style) {
        if (style.fontSize) {
            document.body.style.fontSize =
                String(style.fontSize) + "px";
        }

        if (style.sidebarWidth) {
            $("sidebar").style.width =
                Math.max(
                    210,
                    Math.min(
                        600,
                        Number(style.sidebarWidth)
                    )
                ) + "px";
        }

        if (style.terminalHeight) {
            document.querySelector(".bottom").style.height =
                Math.max(
                    150,
                    Math.min(
                        window.innerHeight * .6,
                        Number(style.terminalHeight)
                    )
                ) + "px";
        }

        if (style.editorFontSize) {
            $("editor").style.fontSize =
                String(style.editorFontSize) + "px";
        }

        if (style.wordWrap) {
            $("editor").style.whiteSpace = "pre-wrap";
        } else {
            $("editor").style.whiteSpace = "pre";
        }
    }

    $("refreshButton").addEventListener(
        "click",
        function() {
            loadDirectory(
                state.cwd || "~",
                true
            );
        }
    );

    $("addFileButton").addEventListener(
        "click",
        function() {
            createFile();
        }
    );

    $("saveButton").addEventListener(
        "click",
        function() {
            saveCurrent();
        }
    );

    $("liveCodeButton").addEventListener(
        "click",
        function() {
            toggleLiveCode();
        }
    );

    $("liveCodeClose").addEventListener(
        "click",
        function() {
            toggleLiveCode(false);
        }
    );

    $("lintButton").addEventListener(
        "click",
        function() {
            lintCurrent();
        }
    );

    $("editor").addEventListener(
        "input",
        function() {
            if (!state.activePath) {
                return;
            }

            const file = state.openFiles.get(
                state.activePath
            );

            if (file) {
                file.content = $("editor").value;
                file.dirty = true;
            }

            scheduleLint();
            updateLiveCode();
            renderTabs();
        }
    );

    $("editor").addEventListener(
        "keydown",
        function(event) {
            if (event.key === "Tab") {
                event.preventDefault();

                const start = event.target.selectionStart;
                const end = event.target.selectionEnd;

                event.target.value =
                    event.target.value.substring(0, start) +
                    "    " +
                    event.target.value.substring(end);

                event.target.selectionStart = start + 4;
                event.target.selectionEnd = start + 4;

                event.target.dispatchEvent(
                    new Event("input")
                );
            }

            if (
                event.ctrlKey &&
                event.key.toLowerCase() === "s"
            ) {
                event.preventDefault();
                saveCurrent();
            }
        }
    );

    $("terminalInput").addEventListener(
        "keydown",
        function(event) {
            if (event.key === "Enter") {
                event.preventDefault();

                const value = event.target.value + "\n";
                sendTerminalInput(value);
                event.target.value = "";
            }

            if (
                event.key === "c" &&
                event.ctrlKey
            ) {
                sendTerminalInput("\u0003");
            }
        }
    );

    $("clearTerminalButton").addEventListener(
        "click",
        function() {
            $("terminal").textContent = "";
        }
    );

    $("sidebarToggle").addEventListener(
        "click",
        function() {
            $("sidebar").classList.toggle("mobileVisible");
        }
    );

    $("modalCancel").addEventListener(
        "click",
        function() {
            closeModal(null);
        }
    );

    $("modalConfirm").addEventListener(
        "click",
        function() {
            closeModal(
                $("modalInput").value
            );
        }
    );

    $("modalInput").addEventListener(
        "keydown",
        function(event) {
            if (event.key === "Enter") {
                event.preventDefault();
                closeModal(
                    $("modalInput").value
                );
            }

            if (event.key === "Escape") {
                event.preventDefault();
                closeModal(null);
            }
        }
    );

    $("modalBackdrop").addEventListener(
        "click",
        function(event) {
            if (event.target === $("modalBackdrop")) {
                closeModal(null);
            }
        }
    );

    window.addEventListener(
        "keydown",
        function(event) {
            if (
                event.key === "Escape" &&
                $("liveCodePanel").classList.contains("visible")
            ) {
                toggleLiveCode(false);
            }
        }
    );

    document.addEventListener(
        "visibilitychange",
        function() {
            if (!document.hidden) {
                if (
                    !state.terminalSocket ||
                    state.terminalSocket.readyState === WebSocket.CLOSED
                ) {
                    connectTerminal();
                }
            }
        }
    );

    const bootPromise = boot();

    Promise.resolve(bootPromise)
        .catch(function() {
        })
        .finally(function() {
            finishLoading();
        });

    window.setTimeout(
        finishLoading,
        10000
    );
})();
</script>

</body>
</html>
'''

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
        debug=False,
    )
