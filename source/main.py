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
LOADING_LIMIT_MS = 1500

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


def default_state():
    return {
        "openFiles": [],
        "lastFile": None,
        "envEnabled": False
    }


def get_state():
    state = load_json(
        STATE_FILE,
        default_state()
    )

    if not isinstance(state, dict):
        state = default_state()

    if not isinstance(
        state.get("openFiles"),
        list
    ):
        state["openFiles"] = []

    if "lastFile" not in state:
        state["lastFile"] = None

    state["envEnabled"] = bool(
        state.get(
            "envEnabled",
            False
        )
    )

    return state


def set_env_enabled(enabled):
    state = get_state()

    state["envEnabled"] = bool(
        enabled
    )

    atomic_json_write(
        STATE_FILE,
        state
    )

    return state["envEnabled"]


def env_enabled():
    return get_state()["envEnabled"]


def is_env_file(path):
    name = os.path.basename(
        os.path.realpath(path)
    ).lower()

    return (
        name == ".env"
        or name.startswith(".env.")
    )


def protect_env_content(content):
    result = []

    for line in content.splitlines(
        keepends=True
    ):
        newline = ""
        raw = line

        if raw.endswith("\r\n"):
            raw = raw[:-2]
            newline = "\r\n"

        elif (
            raw.endswith("\n")
            or raw.endswith("\r")
        ):
            newline = raw[-1]
            raw = raw[:-1]

        if (
            not raw.strip()
            or raw.lstrip().startswith("#")
            or "=" not in raw
        ):
            result.append(
                raw + newline
            )
            continue

        key, _, _ = raw.partition("=")

        result.append(
            key
            + "=[value hidden]"
            + newline
        )

    return "".join(result)


def ensure_data_files():
    os.makedirs(
        SCRIPTS_SAVE,
        exist_ok=True
    )

    os.makedirs(
        STYLE_DIR,
        exist_ok=True
    )

    if not os.path.exists(
        STYLE_FILE
    ):
        atomic_json_write(
            STYLE_FILE,
            DEFAULT_STYLE
        )

    if not os.path.exists(
        STATE_FILE
    ):
        atomic_json_write(
            STATE_FILE,
            default_state()
        )


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
                "path": os.path.realpath(
                    SHARED
                ),
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
        if (
            real == root
            or real.startswith(
                root + os.sep
            )
        ):
            return real

    raise PermissionError(
        "Path outside allowed Termux roots"
    )


def safe_path(path):
    if not path:
        return HOME

    if not os.path.isabs(path):
        path = os.path.join(
            HOME,
            path
        )

    return allowed(path)


def rel_label(path):
    real = os.path.realpath(path)

    if real == HOME:
        return "~"

    shared = os.path.realpath(
        SHARED
    )

    if real == shared:
        return "/storage/emulated/0"

    if real.startswith(
        HOME + os.sep
    ):
        return (
            "~/"
            + os.path.relpath(
                real,
                HOME
            )
        )

    if real.startswith(
        shared + os.sep
    ):
        return (
            "/storage/emulated/0/"
            + os.path.relpath(
                real,
                shared
            )
        )

    return real


def file_icon(
    name,
    directory=False
):
    if directory:
        return "fa-solid fa-folder"

    lower = name.lower()

    if (
        lower == ".env"
        or lower.startswith(".env.")
    ):
        return EXTENSIONS["env"]

    ext = (
        lower.rsplit(".", 1)[-1]
        if "." in lower
        else ""
    )

    return EXTENSIONS.get(
        ext,
        "fa-solid fa-file"
    )


def list_directory(path):
    directory = safe_path(path)

    if not os.path.isdir(directory):
        raise FileNotFoundError(
            directory
        )

    entries = []

    with os.scandir(directory) as scan:
        for entry in scan:
            if len(entries) >= MAX_SCAN_ITEMS:
                break

            if (
                not entry.is_dir(
                    follow_symlinks=False
                )
                and entry.name in IGNORED_FILE_NAMES
            ):
                continue

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
                        "hidden": (
                            entry.name.startswith(".")
                        ),
                        "symlink": (
                            entry.is_symlink()
                        ),
                        "protected": (
                            not is_dir
                            and is_env_file(
                                entry.path
                            )
                            and not env_enabled()
                        ),
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
        with open(
            path,
            "rb"
        ) as handle:
            sample = handle.read(
                8192
            )

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
        with os.fdopen(
            fd,
            "wb"
        ) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(
                handle.fileno()
            )

        os.replace(
            temp,
            path
        )

    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def generic_lint(content):
    errors = []

    pairs = {
        "(": ")",
        "[": "]",
        "{": "}"
    }

    stack = []

    strings = False
    quote = None
    escaped = False

    line = 0
    column = 0

    for char in content:
        if char == "\n":
            line += 1
            column = 0
            continue

        if strings:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                strings = False
                quote = None

            column += 1
            continue

        if char in ("'", '"', "`"):
            strings = True
            quote = char
            column += 1
            continue

        if char in pairs:
            stack.append(
                (
                    char,
                    line,
                    column
                )
            )

        elif char in pairs.values():
            if not stack:
                errors.append(
                    {
                        "line": line,
                        "column": column,
                        "message": (
                            "Unexpected closing "
                            f"character '{char}'"
                        )
                    }
                )
                return errors

            opening, opening_line, opening_column = stack.pop()

            if pairs[opening] != char:
                errors.append(
                    {
                        "line": line,
                        "column": column,
                        "message": (
                            f"Expected '{pairs[opening]}' "
                            f"for '{opening}' opened at "
                            f"{opening_line + 1}:"
                            f"{opening_column + 1}"
                        )
                    }
                )
                return errors

        column += 1

    if strings:
        errors.append(
            {
                "line": line,
                "column": column,
                "message": "Unterminated string"
            }
        )

    if stack:
        opening, opening_line, opening_column = stack[-1]

        errors.append(
            {
                "line": opening_line,
                "column": opening_column,
                "message": (
                    f"Unclosed '{opening}'"
                )
            }
        )

    return errors


def parse_lint_error(text, executable):
    message = text.strip().splitlines()

    if not message:
        return {
            "line": 0,
            "column": 0,
            "message": (
                f"{executable} reported an error"
            )
        }

    for line in message:
        match = re.search(
            r"(?:line|:)(\d+)(?::(\d+))?",
            line,
            re.IGNORECASE
        )

        if match:
            return {
                "line": max(
                    0,
                    int(match.group(1)) - 1
                ),
                "column": max(
                    0,
                    int(match.group(2) or 1) - 1
                ),
                "message": line.strip()
            }

    return {
        "line": 0,
        "column": 0,
        "message": message[-1]
    }


def run_lint(content, filename):
    ext = Path(filename).suffix.lower()

    errors = generic_lint(content)

    if errors:
        return errors

    if ext == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            return [
                {
                    "line": max(
                        0,
                        exc.lineno - 1
                    ),
                    "column": max(
                        0,
                        exc.colno - 1
                    ),
                    "message": exc.msg
                }
            ]

        return []

    executable_checks = []

    if ext == ".py":
        executable_checks.append(
            (
                "python",
                [
                    "python",
                    "-c",
                    "compile(open(__import__('sys').argv[1], encoding='utf-8').read(), __import__('sys').argv[1], 'exec')"
                ]
            )
        )

        executable_checks.append(
            (
                "python3",
                [
                    "python3",
                    "-c",
                    "compile(open(__import__('sys').argv[1], encoding='utf-8').read(), __import__('sys').argv[1], 'exec')"
                ]
            )
        )

    elif ext in {
        ".js",
        ".mjs",
        ".cjs"
    }:
        executable_checks.append(
            (
                "node",
                [
                    "node",
                    "--check"
                ]
            )
        )

    elif ext in {
        ".sh",
        ".bash"
    }:
        executable_checks.append(
            (
                "bash",
                [
                    "bash",
                    "-n"
                ]
            )
        )

    elif ext == ".zsh":
        executable_checks.append(
            (
                "zsh",
                [
                    "zsh",
                    "-n"
                ]
            )
        )

    elif ext == ".php":
        executable_checks.append(
            (
                "php",
                [
                    "php",
                    "-l"
                ]
            )
        )

    elif ext == ".rb":
        executable_checks.append(
            (
                "ruby",
                [
                    "ruby",
                    "-c"
                ]
            )
        )

    elif ext == ".pl":
        executable_checks.append(
            (
                "perl",
                [
                    "perl",
                    "-c"
                ]
            )
        )

    if executable_checks:
        temp_path = None

        try:
            fd, temp_path = tempfile.mkstemp(
                prefix=".vstemu-lint-",
                suffix=ext or ".txt"
            )

            with os.fdopen(
                fd,
                "w",
                encoding="utf-8"
            ) as handle:
                handle.write(content)

            last_missing = True

            for executable, command in executable_checks:
                if shutil.which(executable) is None:
                    continue

                last_missing = False

                full_command = list(command)
                full_command.append(
                    temp_path
                )

                try:
                    completed = subprocess.run(
                        full_command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=2
                    )

                except (
                    OSError,
                    subprocess.SubprocessError
                ):
                    continue

                if completed.returncode != 0:
                    return [
                        parse_lint_error(
                            (
                                completed.stderr
                                or ""
                            )
                            + "\n"
                            + (
                                completed.stdout
                                or ""
                            ),
                            executable
                        )
                    ]

                return []

            if last_missing:
                return []

        finally:
            if (
                temp_path
                and os.path.exists(temp_path)
            ):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    return []


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

        if os.path.basename(path) in IGNORED_FILE_NAMES:
            return jsonify(
                {
                    "error": (
                        "This file is ignored "
                        "by VStermu-x"
                    )
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

        protected = (
            is_env_file(path)
            and not env_enabled()
        )

        if protected:
            content = protect_env_content(
                content
            )

        return jsonify(
            {
                "path": path,
                "content": content,
                "size": size,
                "mtime": os.path.getmtime(path),
                "protected": protected,
                "envEnabled": env_enabled(),
                "notice": (
                    ENV_NOTICE
                    if protected
                    else ""
                ),
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
        payload = request.get_json(
            force=True
        )

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

        if not isinstance(
            content,
            str
        ):
            return jsonify(
                {
                    "error": (
                        "Content must be text"
                    )
                }
            ), 400

        if (
            is_env_file(path)
            and not env_enabled()
        ):
            return jsonify(
                {
                    "error": (
                        "The .env editor is protected. "
                        "Enable .env values first."
                    )
                }
            ), 403

        if (
            os.path.basename(path)
            in IGNORED_FILE_NAMES
        ):
            return jsonify(
                {
                    "error": (
                        "This file is ignored "
                        "by VStermu-x"
                    )
                }
            ), 403

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
        payload = request.get_json(
            force=True
        )

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
        payload = request.get_json(
            force=True
        )

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
        payload = request.get_json(
            force=True
        )

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
    return jsonify(
        load_json(
            STYLE_FILE,
            DEFAULT_STYLE
        )
    )


@app.put("/api/style")
def api_style_write():
    payload = request.get_json(
        force=True
    )

    style = dict(
        DEFAULT_STYLE
    )

    style.update(
        {
            key: value
            for key, value in payload.items()
            if key in DEFAULT_STYLE
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
        get_state()
    )


@app.put("/api/state")
def api_state_write():
    payload = request.get_json(
        force=True
    )

    state = get_state()

    state["openFiles"] = (
        payload.get(
            "openFiles",
            []
        )[-20:]
    )

    state["lastFile"] = payload.get(
        "lastFile"
    )

    if "envEnabled" in payload:
        state["envEnabled"] = bool(
            payload["envEnabled"]
        )

    atomic_json_write(
        STATE_FILE,
        state
    )

    return jsonify(state)


@app.get("/api/env/status")
def api_env_status():
    return jsonify(
        {
            "enabled": env_enabled(),
            "notice": ENV_NOTICE
        }
    )


@app.post("/api/env/set")
def api_env_set():
    payload = request.get_json(
        force=True
    )

    enabled = bool(
        payload.get(
            "enabled",
            False
        )
    )

    value = set_env_enabled(
        enabled
    )

    return jsonify(
        {
            "ok": True,
            "enabled": value
        }
    )


@app.post("/api/lint")
def api_lint():
    try:
        payload = request.get_json(
            force=True
        )

        content = payload.get(
            "content",
            ""
        )

        filename = os.path.basename(
            str(
                payload.get(
                    "filename",
                    "untitled.txt"
                )
            )
        )

        if not isinstance(
            content,
            str
        ):
            return jsonify(
                {
                    "errors": [
                        {
                            "line": 0,
                            "column": 0,
                            "message": (
                                "Content must be text"
                            )
                        }
                    ]
                }
            )

        if (
            filename in IGNORED_FILE_NAMES
            or is_env_file(filename)
        ):
            return jsonify(
                {
                    "errors": []
                }
            )

        if len(
            content.encode("utf-8")
        ) > MAX_FILE_SIZE:
            return jsonify(
                {
                    "errors": [
                        {
                            "line": 0,
                            "column": 0,
                            "message": (
                                "Lint skipped because "
                                "the file is too large"
                            )
                        }
                    ]
                }
            )

        return jsonify(
            {
                "errors": run_lint(
                    content,
                    filename
                )[:10]
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "errors": [
                    {
                        "line": 0,
                        "column": 0,
                        "message": str(exc)
                    }
                ]
            }
        ), 500


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
            "envEnabled": env_enabled(),
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

                os.dup2(
                    slave,
                    0
                )

                os.dup2(
                    slave,
                    1
                )

                os.dup2(
                    slave,
                    2
                )

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

    def set_size(
        self,
        cols,
        rows
    ):
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
                os.close(
                    self.fd
                )

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

            if isinstance(
                message,
                bytes
            ):
                message = message.decode(
                    "utf-8",
                    errors="replace"
                )

            try:
                packet = json.loads(
                    message
                )

            except Exception:
                packet = {
                    "type": "input",
                    "data": message
                }

            kind = packet.get(
                "type"
            )

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

                    session.write(
                        command
                    )

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
<title>VStermu-x</title>
<link rel="icon" href="https://raw.githubusercontent.com/joaoTYSM/VStermu/refs/heads/main/icon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fira+Code:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/7.0.0/css/all.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/codemirror.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/theme/material-darker.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/theme/dracula.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/theme/eclipse.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/hint/show-hint.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/lint/lint.css">
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




.stretch-loader{
display:flex;
gap:6px;
height:14px;
align-items:center
}

.stretch-loader span{
width:7px;
height:7px;
border-radius:2px;
background:var(--text);
animation:stretchDot 900ms ease-in-out infinite
}

.stretch-loader span:nth-child(2){
animation-delay:120ms
}

.stretch-loader span:nth-child(3){
animation-delay:240ms
}

@keyframes stretchDot{
0%,100%{
height:7px;
transform:scaleX(1)
}
45%{
height:14px;
transform:scaleX(1.8)
}
70%{
height:9px;
transform:scaleX(1.2)
}
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

.tree-row.env-protected .name{
font-style:italic
}

.tree-row.env-protected .file-icon{
color:var(--danger)
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
grid-template-rows:minmax(180px,1fr) 0 var(--term);
position:relative;
overflow:visible
}

.main.live-active{
grid-template-rows:minmax(150px,1fr) minmax(150px,230px) var(--term)
}

.main.terminal-minimized{
grid-template-rows:minmax(180px,1fr) 0 34px
}

.main.live-active.terminal-minimized{
grid-template-rows:minmax(150px,1fr) minmax(150px,230px) 34px
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

.CodeMirror-lint-mark-error,.CodeMirror-lint-mark-warning{
background-image:none!important;
border-bottom:2px wavy var(--danger)
}

.CodeMirror-lint-tooltip{
z-index:500;
background:var(--panel);
border:1px solid var(--border);
color:var(--text);
box-shadow:var(--shadow);
font-size:11px
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

.editor-protection{
position:absolute;
left:12px;
right:12px;
top:10px;
z-index:5;
background:var(--panel);
border:1px solid var(--border);
border-radius:8px;
padding:9px 11px;
font-size:11px;
line-height:1.45;
color:var(--muted);
box-shadow:var(--shadow)
}

.editor-protection strong{
color:var(--text)
}

.live-preview{
min-height:0;
background:var(--panel);
border-top:1px solid var(--border);
border-bottom:1px solid var(--border);
display:flex;
flex-direction:column;
overflow:hidden
}

.live-head{
height:32px;
display:flex;
align-items:center;
padding:0 8px;
background:var(--panel2);
border-bottom:1px solid var(--border);
flex:0 0 32px
}

.live-title{
font-size:11px;
color:var(--muted);
display:flex;
align-items:center;
gap:7px
}

.live-title strong{
color:var(--text);
font-weight:600
}

.live-close{
margin-left:auto
}

.live-frame-wrap{
position:relative;
flex:1;
min-height:0;
background:#fff
}

.live-frame{
width:100%;
height:100%;
border:0;
display:block;
background:#fff
}

.live-output{
position:absolute;
left:8px;
right:8px;
bottom:8px;
max-height:42%;
overflow:auto;
background:#0b0d10eF;
color:#dce8df;
border:1px solid #ffffff18;
border-radius:7px;
padding:7px 9px;
font:11px 'Fira Code',monospace;
white-space:pre-wrap;
pointer-events:none
}

.live-message{
height:100%;
display:flex;
align-items:center;
justify-content:center;
padding:20px;
text-align:center;
color:var(--muted);
font-size:12px
}

.terminal{
min-height:0;
background:#070909;
color:#dce8df;
border-top:1px solid var(--border);
display:flex;
flex-direction:column;
position:relative
}

.terminal-resizer{
height:7px;
cursor:ns-resize;
flex:0 0 7px;
touch-action:none;
position:relative;
z-index:10
}

.terminal-resizer:hover{
background:#ffffff08
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

.terminal.minimized{
height:34px
}

.terminal.minimized .terminal-resizer,
.terminal.minimized .terminal-body{
display:none
}

.terminal-body{
min-height:0;
flex:1
}

.terminal.minimized .term-head{
border-bottom:0
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

.modal-row input,
.modal-row select{
width:100%;
height:39px;
background:var(--bg);
border:1px solid var(--border);
border-radius:8px;
padding:0 11px;
outline:0
}

.modal-row input:focus,
.modal-row select:focus{
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


.setting-toggle{
display:flex;
align-items:center;
justify-content:space-between;
gap:12px;
padding:10px 0
}

.switch{
position:relative;
width:44px;
height:24px;
flex:0 0 auto
}

.switch input{
opacity:0;
width:0;
height:0
}

.slider{
position:absolute;
inset:0;
background:var(--panel2);
border:1px solid var(--border);
border-radius:999px;
cursor:pointer
}

.slider:before{
content:'';
position:absolute;
width:18px;
height:18px;
left:2px;
top:2px;
border-radius:50%;
background:var(--muted);
transition:.18s
}

.switch input:checked+.slider{
background:var(--accent2);
border-color:var(--accent2)
}

.switch input:checked+.slider:before{
transform:translateX(20px);
background:#fff
}

@media(max-width:800px){

#app{
grid-template-rows:48px 1fr
}

.topbar{
height:48px;
padding:0 8px
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
grid-template-rows:minmax(160px,1fr) 0 var(--term)
}

.main.live-active{
grid-template-rows:minmax(140px,1fr) minmax(140px,210px) var(--term)
}

.main.terminal-minimized{
grid-template-rows:minmax(160px,1fr) 0 34px
}

.main.live-active.terminal-minimized{
grid-template-rows:minmax(140px,1fr) minmax(140px,210px) 34px
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
grid-template-rows:minmax(145px,1fr) 0 var(--term)
}

.main.live-active{
grid-template-rows:minmax(125px,1fr) minmax(125px,190px) var(--term)
}

.main.terminal-minimized{
grid-template-rows:minmax(145px,1fr) 0 34px
}

.main.live-active.terminal-minimized{
grid-template-rows:minmax(125px,1fr) minmax(125px,190px) 34px
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

<div class="welcome-label">VStermu-x</div>
<div class="stretch-loader">
<span></span>
<span></span>
<span></span>
</div>
<div class="loading-range">
<div
class="loading-range-fill"
id="loadingRangeFill">
</div>
</div>
<div
class="loading-range-time"
id="loadingRangeTime">
0 / 10 seconds
</div>
</div>
</div>

<div id="app">

<header class="topbar">

<div class="brand">
<img src="https://raw.githubusercontent.com/joaoTYSM/VStermu/refs/heads/main/icon.svg">
<span>VStermu-x</span>
</div>

<div class="top-actions">

<button
class="icon-btn"
id="menuBtn"
title="Explorer">

<i class="fa-solid fa-bars"></i>

</button>

<button
class="icon-btn"
id="saveBtn"
title="Save">

<i class="fa-solid fa-floppy-disk"></i>

</button>

<button
class="icon-btn"
id="settingsBtn"
title="Settings">

<i class="fa-solid fa-gear"></i>

</button>

</div>

</header>

<div class="workspace">

<aside
class="sidebar"
id="sidebar">

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

<div
class="roots"
id="roots">
</div>

<div
class="tree"
id="tree">

<div class="tree-empty">
Loading filesystem...
</div>

</div>

</aside>

<div
class="backdrop"
id="backdrop">
</div>

<main
class="main"
id="mainPanel">

<section class="editor">

<div
class="tabs"
id="tabs">

<div class="tab">
<i class="fa-solid fa-code"></i>
<span>No file open</span>
</div>

<div class="editor-tools">

<button
class="small-btn"
id="executeBtn"
title="Execute">

<i class="fa-solid fa-play"></i>

</button>

<button
class="small-btn"
id="liveBtn"
title="Live Code">

<i class="fa-solid fa-bolt"></i>

</button>

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

<div
class="editor-protection hidden"
id="editorProtection">

<strong>
Protected file
</strong>

<br>

<span id="editorProtectionText"></span>

</div>

<span
class="loading hidden"
id="editorLoading">

Loading...

</span>

</div>

</section>

<section
class="live-preview hidden"
id="livePreview">

<div class="live-head">

<div class="live-title">

<i class="fa-solid fa-bolt"></i>

<strong>
Live Code
</strong>

<span id="liveFileName"></span>

</div>

<button
class="small-btn live-close"
id="liveClose"
title="Close">

<i class="fa-solid fa-xmark"></i>

</button>

</div>

<div class="live-frame-wrap">

<iframe
class="live-frame"
id="liveFrame"
sandbox="allow-scripts">
</iframe>

<pre
class="live-output hidden"
id="liveOutput">
</pre>

<div
class="live-message hidden"
id="liveMessage">
</div>

</div>

</section>

<section
class="terminal"
id="terminalPanel">

<div
class="terminal-resizer"
id="terminalResizer">
</div>

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
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/hint/show-hint.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/hint/javascript-hint.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/hint/anyword-hint.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/edit/closebrackets.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/lint/lint.min.js"></script>
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
let currentFileProtected=false;
let currentFileNotice='';
let saveTimer=null;
let lintTimer=null;
let longTimer=null;
let longTriggered=false;
let modalAction=null;
let envEnabled=false;
let terminalInputBuffer='';
let ws=null;
let reconnectTimer=null;
let resizeTimer=null;
let terminalDragging=false;
let recentFiles=[];
let liveActive=false;
let liveTimer=null;
let liveFrameReady=false;

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
autoCloseBrackets:true,
lint:{
getAnnotations:()=>[]
}
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

const COMPLETIONS={
python:[
'and','as','assert','async','await','break','case','class',
'continue','def','del','elif','else','except','False',
'finally','for','from','global','if','import','in','is',
'lambda','match','None','nonlocal','not','or','pass','raise',
'return','True','try','while','with','yield','self','print',
'str','int','float','bool','bytes','dict','list','set','tuple',
'range','len','open','Exception','ValueError','TypeError',
'RuntimeError','object','super','property','staticmethod',
'classmethod','enumerate','zip','map','filter','sorted',
'reversed','any','all','min','max','sum','abs','round',
'isinstance','issubclass','getattr','setattr','hasattr',
'vars','dir','help','__name__','__file__'
],

javascript:[
'const','let','var','function','return','class','extends',
'new','this','super','if','else','for','while','do','switch',
'case','break','continue','try','catch','finally','throw',
'async','await','import','export','default','from','typeof',
'instanceof','in','of','delete','void','yield','true','false',
'null','undefined','Object','Array','String','Number',
'Boolean','RegExp','Date','Math','JSON','Promise','Map','Set',
'WeakMap','WeakSet','Symbol','Error','console','window',
'document','globalThis','setTimeout','setInterval',
'clearTimeout','clearInterval','fetch'
],

html:[
'html','head','body','title','meta','link','style','script',
'div','span','main','section','header','footer','nav','button',
'input','textarea','select','option','form','label','img','a',
'ul','ol','li','table','thead','tbody','tr','td','th',
'video','audio','canvas','svg','path'
],

css:[
'display','position','absolute','relative','fixed','sticky',
'grid','flex','block','inline','inline-block','width','height',
'min-width','max-width','min-height','max-height','margin',
'padding','border','border-radius','background','color',
'font-size','font-family','font-weight','line-height','opacity',
'transform','transition','animation','box-shadow','overflow',
'cursor','z-index','top','right','bottom','left','gap',
'justify-content','align-items','align-self',
'grid-template-columns','grid-template-rows','media','var',
'calc'
],

shell:[
'cd','pwd','ls','mkdir','rm','cp','mv','touch','cat','echo',
'printf','grep','find','sed','awk','head','tail','less','nano',
'vim','git','python','python3','node','npm','npx','pip','pip3',
'bash','sh','zsh','chmod','clear','exit','export','source',
'env','which','whoami','uname','curl','wget'
],

java:[
'class','interface','enum','extends','implements','public',
'private','protected','static','final','void','int','long',
'double','float','boolean','char','new','return','if','else',
'for','while','try','catch','finally','throw','throws',
'package','import','this','super','null','true','false',
'String','System','Math','Object','List','Map','Set',
'ArrayList','HashMap'
],

c:[
'auto','break','case','char','const','continue','default','do',
'double','else','enum','extern','float','for','goto','if',
'inline','int','long','register','restrict','return','short',
'signed','sizeof','static','struct','switch','typedef','union',
'unsigned','void','volatile','while','NULL','printf','scanf',
'malloc','calloc','realloc','free','memcpy','strlen'
],

cpp:[
'auto','bool','break','case','catch','char','class','const',
'constexpr','continue','default','delete','do','double','else',
'enum','explicit','extern','false','float','for','friend','if',
'inline','int','long','namespace','new','noexcept','nullptr',
'operator','private','protected','public','return','short',
'signed','sizeof','static','struct','switch','template','this',
'throw','true','try','typedef','typename','union','unsigned',
'using','virtual','void','volatile','while','std','string',
'vector','map','set','unordered_map','optional','variant',
'unique_ptr','shared_ptr'
],

rust:[
'fn','let','mut','pub','struct','enum','impl','trait','match',
'if','else','loop','while','for','in','return','use','mod',
'crate','self','Self','move','async','await','dyn','where',
'const','static','type','as','ref','true','false','Option',
'Result','String','Vec','HashMap','HashSet','Box','Rc','Arc',
'println','format','panic'
],

go:[
'package','import','func','var','const','type','struct',
'interface','map','chan','go','defer','select','case',
'default','if','else','for','range','switch','return','break',
'continue','fallthrough','nil','true','false','string','int',
'int64','float64','bool','byte','rune','error','fmt','context',
'time','os','io','http'
],

sql:[
'SELECT','FROM','WHERE','INSERT','INTO','VALUES','UPDATE','SET',
'DELETE','CREATE','ALTER','DROP','TABLE','DATABASE','INDEX',
'JOIN','LEFT','RIGHT','INNER','OUTER','FULL','ON','GROUP','BY',
'ORDER','HAVING','LIMIT','OFFSET','AS','AND','OR','NOT','NULL',
'IS','IN','LIKE','BETWEEN','UNION','ALL','DISTINCT','COUNT',
'SUM','AVG','MIN','MAX','CASE','WHEN','THEN','ELSE','END'
],

json:[
'true',
'false',
'null'
]
};

const LIBRARY_COMPLETIONS={
'discord.py':[
'discord',
'discord.Client',
'discord.Bot',
'discord.AutoShardedClient',
'discord.Intents',
'discord.Message',
'discord.User',
'discord.Member',
'discord.Guild',
'discord.Channel',
'discord.TextChannel',
'discord.VoiceChannel',
'discord.Thread',
'discord.Embed',
'discord.File',
'discord.SelectOption',
'discord.ui',
'discord.ui.View',
'discord.ui.Modal',
'discord.ui.Button',
'discord.ui.Select',
'discord.Interaction',
'discord.app_commands',
'discord.ext',
'discord.ext.commands',
'commands.Bot',
'commands.Cog',
'commands.Context',
'commands.command',
'commands.hybrid_command',
'commands.hybrid_group',
'app_commands.command',
'app_commands.describe',
'app_commands.choices',
'app_commands.Group',
'tasks.loop',
'commands.Bot.tree',
'bot.tree.sync',
'bot.add_cog',
'bot.run',
'message.author',
'message.channel',
'message.guild',
'message.content',
'interaction.response.send_message',
'interaction.followup.send',
'interaction.user',
'guild.members',
'guild.channels'
],

'discord.js':[
'Client',
'GatewayIntentBits',
'Partials',
'Collection',
'REST',
'Routes',
'Events',
'EmbedBuilder',
'AttachmentBuilder',
'ButtonBuilder',
'ButtonStyle',
'ActionRowBuilder',
'StringSelectMenuBuilder',
'ModalBuilder',
'TextInputBuilder',
'TextInputStyle',
'SlashCommandBuilder',
'PermissionFlagsBits',
'ChannelType',
'PermissionsBitField',
'Guild',
'GuildMember',
'Message',
'ChatInputCommandInteraction',
'ClientReady',
'Events.ClientReady',
'client.login',
'client.channels.fetch',
'interaction.reply',
'interaction.followUp',
'interaction.deferReply',
'message.reply',
'guild.members.fetch',
'guild.channels.fetch'
],

'flask':[
'Flask',
'request',
'jsonify',
'Response',
'render_template',
'send_file',
'redirect',
'url_for',
'session',
'make_response',
'abort',
'Blueprint'
],

'fastapi':[
'FastAPI',
'Request',
'Response',
'HTTPException',
'Depends',
'Query',
'Path',
'Body',
'Header',
'Cookie',
'File',
'UploadFile',
'WebSocket',
'WebSocketDisconnect',
'BackgroundTasks'
],

'requests':[
'requests.get',
'requests.post',
'requests.put',
'requests.patch',
'requests.delete',
'requests.Session',
'requests.headers',
'requests.Timeout',
'requests.exceptions.RequestException'
],

'aiohttp':[
'aiohttp.ClientSession',
'aiohttp.ClientTimeout',
'aiohttp.ClientResponse',
'aiohttp.web',
'web.Application',
'web.get',
'web.post',
'ClientConnectorError'
],

'asyncio':[
'asyncio.run',
'asyncio.create_task',
'asyncio.gather',
'asyncio.sleep',
'asyncio.wait',
'asyncio.Event',
'asyncio.Lock',
'asyncio.Queue',
'asyncio.Semaphore'
],

'os':[
'os.environ',
'os.getenv',
'os.getcwd',
'os.chdir',
'os.path',
'os.path.join',
'os.path.exists',
'os.makedirs',
'os.remove',
'os.rename',
'os.scandir',
'os.system',
'os.execvpe'
],

'pathlib':[
'Path',
'Path.exists',
'Path.read_text',
'Path.write_text',
'Path.iterdir',
'Path.glob',
'Path.mkdir',
'Path.unlink',
'PurePath'
],

'json':[
'json.dumps',
'json.loads',
'json.dump',
'json.load',
'json.JSONDecodeError'
],

'shutil':[
'shutil.copy',
'shutil.copytree',
'shutil.move',
'shutil.rmtree',
'shutil.which'
],

'subprocess':[
'subprocess.run',
'subprocess.Popen',
'subprocess.call',
'subprocess.check_call',
'subprocess.check_output',
'subprocess.PIPE',
'subprocess.DEVNULL',
'subprocess.TimeoutExpired'
],

'node:fs':[
'fs.readFile',
'fs.readFileSync',
'fs.writeFile',
'fs.writeFileSync',
'fs.existsSync',
'fs.mkdir',
'fs.mkdirSync',
'fs.readdir',
'fs.readdirSync',
'fs.rm',
'fs.rmSync',
'fs.rename',
'fs.renameSync'
],

'node:path':[
'path.join',
'path.resolve',
'path.basename',
'path.dirname',
'path.extname',
'path.parse',
'path.normalize',
'path.relative'
],

'express':[
'express',
'express.Router',
'router.get',
'router.post',
'router.put',
'router.delete',
'app.use',
'app.listen',
'request',
'response',
'next'
],

'react':[
'React',
'useState',
'useEffect',
'useMemo',
'useCallback',
'useRef',
'useContext',
'useReducer',
'createContext',
'createElement',
'Fragment'
],

'vue':[
'ref',
'reactive',
'computed',
'watch',
'onMounted',
'onUnmounted',
'defineComponent',
'createApp'
],

'numpy':[
'np.array',
'np.zeros',
'np.ones',
'np.arange',
'np.linspace',
'np.mean',
'np.sum',
'np.max',
'np.min',
'np.reshape'
],

'pandas':[
'pd.DataFrame',
'pd.Series',
'pd.read_csv',
'pd.read_json',
'pd.read_excel',
'DataFrame.head',
'DataFrame.tail',
'DataFrame.drop',
'DataFrame.groupby',
'DataFrame.merge'
],

'tkinter':[
'tkinter.Tk',
'tkinter.Frame',
'tkinter.Label',
'tkinter.Button',
'tkinter.Entry',
'tkinter.Text',
'tkinter.Canvas',
'tkinter.messagebox',
'tkinter.filedialog'
]
};

function toast(message){
$('toast').textContent=message;
$('toast').classList.add('show');

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
const e=path.split('.').pop().toLowerCase();

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

async function loadStyle(){
style=await api(
'/api/style'
);

applyStyle();
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

async function loadEnvStatus(){
const d=await api(
'/api/env/status'
);

envEnabled=!!d.enabled;
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

async function buildDir(
path,
depth
){
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
class="tree-row ${isDir?'dir':''} ${item.protected?'env-protected':''} ${selectedPath===item.path?'selected':''}"
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

function isEnvClient(path){
const name=
String(path)
.split('/')
.pop()
.toLowerCase();

return (
name==='.env'
||
name.startsWith('.env.')
);
}

function isIgnoredClient(path){
const name=
String(path)
.split('/')
.pop();

return name===
'vstermu-installer.py';
}

function fileIconClient(path){
const e=
path
.split('/')
.pop()
.toLowerCase();

if(
e==='.env'
||
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

function rememberRecent(path){
if(
!path
||
isIgnoredClient(path)
||
(
isEnvClient(path)
&&
!envEnabled
)
)
return;

recentFiles=[
path,
...recentFiles.filter(
item=>item!==path
)
].slice(
0,
20
);

renderTabs();
saveState();
}

function forgetRecent(path){
recentFiles=
recentFiles.filter(
item=>item!==path
);

renderTabs();
saveState();
}

function renderTabs(){
const tabs=$('tabs');

const items=
recentFiles.filter(
path=>!isIgnoredClient(path)
);

if(!items.length){

tabs.innerHTML=`
<div class="tab">
<i class="fa-solid fa-code"></i>
<span>No file open</span>
</div>

<div class="editor-tools">

<button
class="small-btn"
id="executeBtn"
title="Execute">

<i class="fa-solid fa-play"></i>

</button>

<button
class="small-btn"
id="liveBtn"
title="Live Code">

<i class="fa-solid fa-bolt"></i>

</button>

<button
class="small-btn"
id="fileConfigBtn"
title="File settings">

<i class="fa-solid fa-sliders"></i>

</button>

</div>
`;

}else{

tabs.innerHTML=
items.map(
path=>
`
<div
class="tab ${path===currentFile?'active':''}"
data-recent-path="${encodeURIComponent(path)}">

${icon(fileIconClient(path))}

<span>
${escapeHtml(
path.split('/').pop()
)}
</span>

${
path===currentFile
?
'<span class="tab-close" data-close-path="'
+
encodeURIComponent(path)
+
'">×</span>'
:
''
}

</div>
`
).join('')
+
`
<div class="editor-tools">

<button
class="small-btn"
id="executeBtn"
title="Execute">

<i class="fa-solid fa-play"></i>

</button>

<button
class="small-btn"
id="liveBtn"
title="Live Code">

<i class="fa-solid fa-bolt"></i>

</button>

<button
class="small-btn"
id="fileConfigBtn"
title="File settings">

<i class="fa-solid fa-sliders"></i>

</button>

</div>
`;
}

document
.querySelectorAll(
'[data-recent-path]'
)
.forEach(
tab=>
tab.onclick
=>
openFile(
decodeURIComponent(
tab.dataset.recentPath
)
)
);

document
.querySelectorAll(
'[data-close-path]'
)
.forEach(
btn=>
btn.onclick=e=>{
e.stopPropagation();

closeFile(
decodeURIComponent(
btn.dataset.closePath
)
);
}
);

$('executeBtn').onclick=
executeCurrentFile;

$('liveBtn').onclick=
toggleLiveCode;

$('fileConfigBtn').onclick=
fileSettings;

updateLiveButton();
}

async function openFile(path){
if(
isIgnoredClient(path)
){
toast(
'This file is ignored by VStermu-x'
);
return;
}

$('editorLoading')
.classList.remove(
'hidden'
);

$('emptyEditor')
.classList.add(
'hidden'
);

$('editorProtection')
.classList.add(
'hidden'
);

editor.setOption(
'readOnly',
false
);

currentFileProtected=
false;

try{

const d=
await api(
'/api/read?path='
+
encodeURIComponent(path)
);

currentFile=
path;

currentParent=
path.substring(
0,
path.lastIndexOf('/')
)
||
'/';

currentFileProtected=
!!d.protected;

currentFileNotice=
d.notice||'';

editor.setOption(
'mode',
modeFor(path)
);

editor.setOption(
'readOnly',
currentFileProtected
?'nocursor'
:false
);

editor.setValue(
d.content
);

editor.clearHistory();

if(
currentFileProtected
){

$('editorProtectionText')
.textContent=
currentFileNotice
||
'This file is protected.';

$('editorProtection')
.classList.remove(
'hidden'
);

toast(
'The .env values are protected'
);
}

rememberRecent(
path
);

editor.focus();

scheduleLint();

updateLiveCode();

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

function closeFile(path=currentFile){
const closing=
path||
currentFile;

if(!closing)
return;

forgetRecent(
closing
);

if(
closing===currentFile
){

currentFile=null;
currentFileProtected=false;

$('editorProtection')
.classList.add(
'hidden'
);

editor.setOption(
'readOnly',
false
);

editor.setValue('');

clearLintMarks();

$('emptyEditor')
.classList.remove(
'hidden'
);

if(
liveActive
)
updateLiveCode();
}

if(!recentFiles.length){

renderTabs();

}else if(!currentFile){

const next=
recentFiles[0];

openFile(next);
}
}

function saveFile(){
if(!currentFile)
return;

if(
currentFileProtected
)
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
e=>toast(
e.message
)
);
}

editor.on(
'change',
()=>{
if(
!currentFile
||
currentFileProtected
)
return;

clearTimeout(
saveTimer
);

saveTimer=
setTimeout(
saveFile,
650
);

scheduleLint();

scheduleAutocomplete();

if(liveActive){
clearTimeout(
liveTimer
);

liveTimer=
setTimeout(
updateLiveCode,
120
);
}
}
);

function showContext(
x,
y
){

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
b=>
b.style.display='flex'
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

return currentRoot?.path||
HOME;
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
'Created '
+
name
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
()=>
$('modalName')?.focus(),
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
)
currentFile=
d.path;

recentFiles=
recentFiles.map(
item=>
item===oldPath
?d.path
:item
);

selectedPath=
d.path;

renderTabs();

await renderTree();

saveState();

closeModal();

toast(
'Renamed'
);
}
);

setTimeout(
()=>
$('modalName')?.focus(),
60
);
}

function deleteSelected(){

if(
!selectedPath
||
selectedPath===
currentRoot?.path
)
return;

openModal(
'Delete',

`
<div
style="color:var(--danger);font-size:13px;line-height:1.5">

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
currentFile===
selectedPath
)
closeFile(
selectedPath
);
else
forgetRecent(
selectedPath
);

selectedPath=
currentRoot.path;

await renderTree();

closeModal();

toast(
'Deleted'
);

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

function shellQuoteClient(value){
return "'"
+
String(value).replace(
/'/g,
"'\\''"
)
+
"'";
}

function executionCommand(path){

const ext=
path.split('.')
.pop()
.toLowerCase();

const q=
shellQuoteClient(path);

const map={
py:`python ${q}`,
js:`node ${q}`,
mjs:`node ${q}`,
cjs:`node ${q}`,
ts:`npx tsx ${q}`,
tsx:`npx tsx ${q}`,
jsx:`node ${q}`,
sh:`bash ${q}`,
bash:`bash ${q}`,
zsh:`zsh ${q}`,
fish:`fish ${q}`,
php:`php ${q}`,
rb:`ruby ${q}`,
pl:`perl ${q}`,
lua:`lua ${q}`,
go:`go run ${q}`,
java:`javac ${q} && java ${shellQuoteClient(path.replace(/\.java$/,''))}`,
c:`gcc ${q} -o ${shellQuoteClient(path+'.out')} && ${shellQuoteClient(path+'.out')}`,
cpp:`g++ ${q} -o ${shellQuoteClient(path+'.out')} && ${shellQuoteClient(path+'.out')}`,
rs:`rustc ${q} -o ${shellQuoteClient(path+'.out')} && ${shellQuoteClient(path+'.out')}`
};

return map[ext]||null;
}

function executeCurrentFile(){

if(!currentFile){
toast(
'No file selected'
);
return;
}

if(
currentFileProtected
||
isIgnoredClient(currentFile)
){
toast(
'This file cannot be executed'
);
return;
}

const command=
executionCommand(
currentFile
);

if(!command){
toast(
'No execution command is configured for this language'
);
return;
}

restoreTerminal();

const folder=
currentParent
||
currentFile.substring(
0,
currentFile.lastIndexOf('/')
)
||
HOME;

sendWS(
{
type:'cwd',
path:folder
}
);

setTimeout(
()=>
sendWS(
{
type:'input',
data:command+'\n'
}
),
80
);

toast(
'Executing '
+
currentFile.split('/').pop()
);
}

function updateLiveButton(){

const button=
$('liveBtn');

if(!button)
return;

button.style.color=
liveActive
?'var(--accent)'
:'var(--muted)';

button.title=
liveActive
?'Close Live Code'
:'Live Code';
}

function toggleLiveCode(){

if(!currentFile){
toast(
'Open a file first'
);
return;
}

liveActive=
!liveActive;

$('livePreview')
.classList.toggle(
'hidden',
!liveActive
);

$('mainPanel')
.classList.toggle(
'live-active',
liveActive
);

updateLiveButton();

if(liveActive)
updateLiveCode();

setTimeout(
fitTerminal,
80
);
}

function liveLanguage(path){

const ext=
path.split('.')
.pop()
.toLowerCase();

if(
[
'html',
'htm',
'svg'
].includes(ext)
)
return 'html';

if(
[
'css',
'scss',
'sass',
'less'
].includes(ext)
)
return 'css';

if(
[
'js',
'mjs',
'cjs',
'ts',
'jsx',
'tsx'
].includes(ext)
)
return 'javascript';

if(
[
'json',
'txt',
'md'
].includes(ext)
)
return 'text';

return ext;
}

function buildLiveDocument(
path,
code
){

const lang=
liveLanguage(path);

if(lang==='html'){

return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
html,body{
margin:0;
min-height:100%;
font-family:Inter,Arial,sans-serif
}
body{
padding:16px;
box-sizing:border-box
}
</style>
</head>
<body>
${code}
<script>
const send=(type,data)=>
parent.postMessage(
{
source:'vstermu-live',
type,
data
},
'*'
);

const oldLog=console.log;
const oldWarn=console.warn;
const oldError=console.error;

console.log=(...a)=>{
oldLog(...a);
send(
'console',
a.map(
x=>
typeof x==='string'
?x
:JSON.stringify(x)
).join(' ')
);
};

console.warn=(...a)=>{
oldWarn(...a);
send(
'console',
'Warning: '
+
a.map(
x=>String(x)
).join(' ')
);
};

console.error=(...a)=>{
oldError(...a);
send(
'console',
'Error: '
+
a.map(
x=>String(x)
).join(' ')
);
};

window.onerror=(m)=>
send(
'console',
'Error: '
+
m
);
<\/script>
</body>
</html>`;
}

if(lang==='css'){

return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
${code}
</style>
</head>
<body>
<div class="live-message">
CSS preview is active. Add HTML to an HTML file for a full page preview.
</div>
</body>
</html>`;
}

if(lang==='javascript'){

const escaped=
code.replace(
/<\/script/gi,
'<\\/script'
);

return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
body{
margin:0;
padding:16px;
font-family:Inter,Arial,sans-serif;
background:#fff;
color:#111
}

pre{
white-space:pre-wrap;
font:12px monospace
}
</style>
</head>
<body>

<pre id="output"></pre>

<script>
const out=
document.getElementById(
'output'
);

const write=(type,args)=>{
const line=
document.createElement(
'div'
);

line.textContent=
args.map(
x=>{
try{
return typeof x==='string'
?x
:JSON.stringify(x)
}catch(e){
return String(x)
}
}
).join(' ');

out.appendChild(
line
);

parent.postMessage(
{
source:'vstermu-live',
type:'console',
data:line.textContent
},
'*'
);
};

console.log=
(...a)=>
write(
'log',
a
);

console.warn=
(...a)=>
write(
'warn',
[
'Warning:',
...a
]
);

console.error=
(...a)=>
write(
'error',
[
'Error:',
...a
]
);

try{
${escaped}
}catch(error){
write(
'error',
[
'Error:',
error.message
]
);
}
<\/script>

</body>
</html>`;
}

return '';
}

function updateLiveCode(){

if(
!liveActive
||
!currentFile
)
return;

const name=
currentFile
.split('/')
.pop();

$('liveFileName')
.textContent=
name;

$('liveOutput')
.classList.add(
'hidden'
);

$('liveOutput')
.textContent='';

$('liveMessage')
.classList.add(
'hidden'
);

const lang=
liveLanguage(
currentFile
);

if(
[
'html',
'css',
'javascript'
].includes(lang)
){

const doc=
buildLiveDocument(
currentFile,
editor.getValue()
);

$('liveFrame')
.srcdoc=
doc;

}else{

let message=
'Live preview is available for HTML, CSS, and JavaScript.';

if(lang==='py'){

const lines=[];

for(
const match of editor
.getValue()
.matchAll(
/print\s*\(([^\n)]*)\)/g
)
){

const value=
match[1].trim();

if(
(
value.startsWith('"')
&&
value.endsWith('"')
)
||
(
value.startsWith("'")
&&
value.endsWith("'")
)
)
lines.push(
value.slice(
1,
-1
)
);

else if(
/^[-+]?\d+(?:\.\d+)?$/
.test(value)
)
lines.push(value);

else
lines.push(
'print('
+
value
+
')'
);
}

message=
lines.length
?
'Predicted output\n'
+
lines.join('\n')
:
'Python preview is shown as source only. Use Execute to run it in Termux.';
}

$('liveFrame')
.srcdoc='';

$('liveMessage')
.textContent=
message;

$('liveMessage')
.classList.remove(
'hidden'
);
}
}

window.addEventListener(
'message',
event=>{
const data=
event.data;

if(
!data
||
data.source!=='vstermu-live'
)
return;

if(
data.type==='console'
){

const output=
$('liveOutput');

output.classList.remove(
'hidden'
);

output.textContent+=
String(
data.data
)
+
'\n';
}
}
);

function saveState(){

return api(
'/api/state',
{
method:'PUT',
body:JSON.stringify(
{
openFiles:
recentFiles.slice(
0,
20
),
lastFile:
currentFile,
envEnabled
}
)
}
).catch(
()=>{}
);
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

restoreTerminal();

toast(
'Terminal changed to '
+
path
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
.textContent=
title;

$('modalBody')
.innerHTML=
body;

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

<div class="setting-toggle">

<div>

<strong>
Show .env values
</strong>

<div
style="font-size:11px;color:var(--muted);margin-top:4px">

Disabled by default. Turning this off protects all .env values again.

</div>

</div>

<label class="switch">

<input
id="setEnv"
type="checkbox">

<span class="slider"></span>

</label>

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

const requestedEnv=
$('setEnv').checked;

if(
requestedEnv!==envEnabled
){

if(
requestedEnv
&&
!confirm(
'Show .env values in the editor?'
)
){
return;
}

await api(
'/api/env/set',
{
method:'POST',
body:JSON.stringify(
{
enabled:requestedEnv
}
)
}
);

envEnabled=
requestedEnv;
}

await api(
'/api/style',
{
method:'PUT',
body:JSON.stringify(style)
}
);

applyStyle();

closeModal();

if(
currentFile
&&
isEnvClient(currentFile)
)
await openFile(
currentFile
);

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

$('setEnv').checked=
envEnabled;
}

$('settingsBtn').onclick=
openSettings;

$('liveClose').onclick=
()=>{
liveActive=false;

$('livePreview')
.classList.add(
'hidden'
);

$('mainPanel')
.classList.remove(
'live-active'
);

updateLiveButton();

setTimeout(
fitTerminal,
80
);
};

function terminalCommand(line){

const command=
line.trim();

if(
command===
'.env enable'
){

if(envEnabled){

term.writeln(
'\r\n.env values are already enabled.'
);

return true;
}

sendWS(
{
type:'input',
data:'\u0003'
}
);

openModal(
'Enable .env values',

`
<div
style="font-size:13px;line-height:1.5">

This will allow VStermu-x to display .env values in the editor. The setting can be disabled again from Settings.

</div>
`,

async()=>{

await api(
'/api/env/set',
{
method:'POST',
body:JSON.stringify(
{
enabled:true
}
)
}
);

envEnabled=true;

closeModal();

term.writeln(
'\r\n.env values enabled. Reloading VStermu-x...'
);

setTimeout(
()=>
location.href=
location.pathname
+
'?env=enabled',
250
);
}
);

return true;
}

if(
command===
'.env unenable'
){

sendWS(
{
type:'input',
data:'\u0003'
}
);

api(
'/api/env/set',
{
method:'POST',
body:JSON.stringify(
{
enabled:false
}
)
}
)
.then(
()=>{
envEnabled=false;

term.writeln(
'\r\n.env values disabled.'
);

setTimeout(
()=>
location.href=
location.pathname
+
'?env=disabled',
250
);
}
)
.catch(
e=>
toast(
e.message
)
);

return true;
}

if(
command===
'.env status'
){

sendWS(
{
type:'input',
data:'\u0003'
}
);

term.writeln(
'\r\n.env protection: '
+
(
envEnabled
?'enabled'
:'disabled'
)
);

return true;
}

if(
command===
'.vstermu help'
){

sendWS(
{
type:'input',
data:'\u0003'
}
);

term.writeln(
'\r\nVStermu-x commands'
);

term.writeln(
'.env enable     Enable .env values after confirmation'
);

term.writeln(
'.env unenable   Disable .env values'
);

term.writeln(
'.env status     Show .env protection status'
);

term.writeln(
'.vstermu help   Show this command list'
);

term.writeln(
'.vstermu clear  Clear the terminal'
);

term.writeln(
'.vstermu reload Reload the editor'
);

term.writeln(
'.vstermu settings Open Settings'
);

term.writeln(
'.vstermu explorer Open Explorer'
);

return true;
}

if(
command===
'.vstermu clear'
){

sendWS(
{
type:'input',
data:'\u0003'
}
);

term.clear();

return true;
}

if(
command===
'.vstermu reload'
){

sendWS(
{
type:'input',
data:'\u0003'
}
);

location.reload();

return true;
}

if(
command===
'.vstermu settings'
){

sendWS(
{
type:'input',
data:'\u0003'
}
);

openSettings();

return true;
}

if(
command===
'.vstermu explorer'
){

sendWS(
{
type:'input',
data:'\u0003'
}
);

$('sidebar')
.classList.add(
'open'
);

$('backdrop')
.classList.add(
'show'
);

return true;
}

return false;
}

function handleTerminalInput(data){

if(!data)
return false;

if(
data.includes('\r')
||
data.includes('\n')
){

const parts=
data
.replace(
/\r\n/g,
'\n'
)
.replace(
/\r/g,
'\n'
)
.split('\n');

let first=
parts.shift();

if(
parts.length
||
data.endsWith('\n')
){

terminalInputBuffer+=
first;

const custom=
terminalCommand(
terminalInputBuffer
);

terminalInputBuffer='';

if(custom){

if(parts.length){

const rest=
parts.join('\n');

if(rest)
sendWS(
{
type:'input',
data:rest
}
);
}

return true;
}

return false;
}

terminalInputBuffer+=
first;

return false;
}

if(
data==='\x7f'
||
data==='\b'
){

terminalInputBuffer=
terminalInputBuffer.slice(
0,
-1
);

return false;
}

if(
data==='\x03'
||
data==='\x04'
){

terminalInputBuffer='';

return false;
}

if(
data.startsWith('\x1b')
){

terminalInputBuffer='';

return false;
}

if(
data==='\t'
){

terminalInputBuffer='';

return false;
}

if(
/^[\x20-\x7e]+$/.test(data)
){

terminalInputBuffer+=
data;

if(
terminalInputBuffer.length>512
)
terminalInputBuffer=
terminalInputBuffer.slice(
-512
);
}

return false;
}

term.onData(
data=>{
if(
handleTerminalInput(data)
)
return;

sendWS(
{
type:'input',
data
}
);
}
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

if(
$('terminalPanel')
.classList.contains(
'minimized'
)
)
return;

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

function restoreTerminal(){

$('terminalPanel')
.classList.remove(
'minimized'
);

$('mainPanel')
.classList.remove(
'terminal-minimized'
);

$('minTermBtn')
.innerHTML=
icon(
'fa-solid fa-chevron-down'
);

setTimeout(
fitTerminal,
80
);
}

function minimizeTerminal(){

$('terminalPanel')
.classList.add(
'minimized'
);

$('mainPanel')
.classList.add(
'terminal-minimized'
);

$('minTermBtn')
.innerHTML=
icon(
'fa-solid fa-chevron-up'
);

setTimeout(
()=>{
try{
fitAddon.fit();
}catch(e){}
},
80
);
}

$('minTermBtn').onclick=
()=>{
$('terminalPanel')
.classList.contains(
'minimized'
)
?
restoreTerminal()
:
minimizeTerminal();
};

function updateTerminalHeight(
clientY
){

const rect=
$('mainPanel')
.getBoundingClientRect();

const max=
Math.min(
700,
Math.max(
120,
rect.height-145
)
);

const value=
Math.max(
120,
Math.min(
max,
rect.bottom-clientY
)
);

document.documentElement.style.setProperty(
'--term',
value+'px'
);

style.terminalHeight=
Math.round(
value
);

clearTimeout(
resizeTimer
);

resizeTimer=
setTimeout(
()=>{
api(
'/api/style',
{
method:'PUT',
body:JSON.stringify(
{
terminalHeight:
style.terminalHeight
}
)
}
)
.catch(
()=>{}
);

fitTerminal();
},
90
);
}

$('terminalResizer')
.addEventListener(
'pointerdown',
e=>{
if(
$('terminalPanel')
.classList.contains(
'minimized'
)
)
return;

terminalDragging=true;

$('terminalResizer')
.setPointerCapture?.(
e.pointerId
);

document.body.style.userSelect=
'none';
}
);

window.addEventListener(
'pointermove',
e=>{
if(!terminalDragging)
return;

updateTerminalHeight(
e.clientY
);
}
);

window.addEventListener(
'pointerup',
()=>{
if(!terminalDragging)
return;

terminalDragging=false;

document.body.style.userSelect='';

fitTerminal();
}
);

function scheduleAutocomplete(){

if(
currentFileProtected
||
!currentFile
||
currentFile.toLowerCase().endsWith(
'.env'
)
)
return;

clearTimeout(
window.completeTimer
);

window.completeTimer=
setTimeout(
()=>{
const pos=
editor.getCursor();

const ch=
editor.getRange(
{
line:pos.line,
ch:Math.max(
0,
pos.ch-1
)
},
pos
);

if(
/[A-Za-z0-9_.]/.test(ch)
)
showCompletions();
},
120
);
}

function completionPrefix(cm){

const cursor=
cm.getCursor();

const line=
cm.getLine(
cursor.line
);

const before=
line.slice(
0,
cursor.ch
);

const match=
before.match(
/[A-Za-z_$][\w$]*$/
);

return {
prefix:
match
?match[0]
:'',
before
};
}

function inferLibraries(text){

const result=[];

if(
/\bimport\s+discord\b|
from\s+discord\b|
discord\.py/i.test(text)
)
result.push(
'discord.py'
);

if(
/require\(['"]discord\.js|
from\s+['"]discord\.js|
discord\.js/i.test(text)
)
result.push(
'discord.js'
);

if(
/from\s+flask\b|
import\s+flask\b|
Flask\(/.test(text)
)
result.push(
'flask'
);

if(
/from\s+fastapi\b|
FastAPI\(/.test(text)
)
result.push(
'fastapi'
);

if(
/\brequests\./.test(text)
)
result.push(
'requests'
);

if(
/\baiohttp\./.test(text)
)
result.push(
'aiohttp'
);

if(
/\basyncio\./.test(text)
)
result.push(
'asyncio'
);

if(
/\bos\./.test(text)
)
result.push(
'os'
);

if(
/\bPath\b|
pathlib/.test(text)
)
result.push(
'pathlib'
);

if(
/\bjson\./.test(text)
)
result.push(
'json'
);

if(
/\bsubprocess\./.test(text)
)
result.push(
'subprocess'
);

if(
/require\(['"](?:node:)?fs|
from\s+['"]node:fs/.test(text)
)
result.push(
'node:fs'
);

if(
/require\(['"](?:node:)?path|
from\s+['"]node:path/.test(text)
)
result.push(
'node:path'
);

if(
/express\(/.test(text)
)
result.push(
'express'
);

if(
/from\s+['"]react['"]|
import\s+React/.test(text)
)
result.push(
'react'
);

if(
/from\s+['"]vue['"]/.test(text)
)
result.push(
'vue'
);

if(
/\bnumpy\b|
\bnp\./.test(text)
)
result.push(
'numpy'
);

if(
/\bpandas\b|
\bpd\./.test(text)
)
result.push(
'pandas'
);

if(
/\b tkinter\b|
\bt tkinter\b|
\btkin[tT]er\b/.test(text)
)
result.push(
'tkinter'
);

return [
...new Set(
result
)
];
}

function localIdentifiers(text){

const values=
new Set();

for(
const match of text.matchAll(
/\b(?:class|def|function|const|let|var|fn|func|struct|interface|enum|type)\s+([A-Za-z_$][\w$]*)/g
)
)
values.add(
match[1]
);

for(
const match of text.matchAll(
/\b(?:import|from)\s+([A-Za-z_$][\w$.-]*)/g
)
)
values.add(
match[1]
);

return [
...values
];
}

function hintData(cm){

const cursor=
cm.getCursor();

const line=
cm.getLine(
cursor.line
);

const before=
line.slice(
0,
cursor.ch
);

const tokenMatch=
before.match(
/[A-Za-z_$][\w$]*$/
);

const prefix=
tokenMatch
?tokenMatch[0]
:'';

const text=
cm.getValue();

let pool=[];

const lang=
languageKey(
currentFile||''
);

pool=
pool.concat(
COMPLETIONS[lang]
||
COMPLETIONS.javascript
);

for(
const lib of inferLibraries(
text
)
){
pool=
pool.concat(
LIBRARY_COMPLETIONS[lib]
||
[]
);
}

pool=
pool.concat(
localIdentifiers(
text
)
);

if(
/\.([A-Za-z_$][\w$]*)?$/.test(
before
)
){

for(
const lib of Object.values(
LIBRARY_COMPLETIONS
)
){
pool=
pool.concat(
lib
);
}
}

pool=[
...new Set(
pool
)
].filter(
v=>
String(v)
.toLowerCase()
.startsWith(
prefix.toLowerCase()
)
);

const start={
line:cursor.line,
ch:cursor.ch-prefix.length
};

return {
list:
pool.slice(
0,
120
),
from:start,
to:cursor
};
}

function showCompletions(){

if(
!currentFile
||
currentFileProtected
||
currentFile.toLowerCase().endsWith(
'.env'
)
)
return;

CodeMirror.showHint(
editor,
hintData,
{
completeSingle:false,
alignWithWord:true,
closeOnUnfocus:true
}
);
}

editor.setOption(
'extraKeys',
{
'Ctrl-S':saveFile,
'Cmd-S':saveFile,
'Ctrl-Space':showCompletions,
'Ctrl- ':showCompletions
}
);

function clearLintMarks(){

if(
editor._vstermuLintMarks
){

editor._vstermuLintMarks
.forEach(
mark=>mark.clear()
);
}

editor._vstermuLintMarks=[];
}

function renderLintErrors(
errors
){

clearLintMarks();

if(
!errors
||
!errors.length
||
!currentFile
||
currentFileProtected
)
return;

editor._vstermuLintMarks=
errors.slice(
0,
10
).map(
err=>{

const line=
Math.max(
0,
Math.min(
err.line,
editor.lineCount()-1
)
);

const ch=
Math.max(
0,
Math.min(
err.column,
editor.getLine(
line
).length
)
);

const end=
Math.min(
editor.getLine(
line
).length,
Math.max(
ch+1,
ch+12
)
);

return editor.markText(
{
line,
ch
},
{
line,
ch:end
},
{
className:
'CodeMirror-lint-mark-error',
title:
err.message,
clearOnEnter:false
}
);
}
);
}

function scheduleLint(){

if(
!currentFile
||
currentFileProtected
||
currentFile.toLowerCase().endsWith(
'.env'
)
||
currentFile.split('/').pop()===
'vstermu-installer.py'
)
return;

clearTimeout(
lintTimer
);

lintTimer=
setTimeout(
runLintRequest,
450
);
}

async function runLintRequest(){

if(
!currentFile
||
currentFileProtected
)
return;

try{

const d=
await api(
'/api/lint',
{
method:'POST',
body:JSON.stringify(
{
filename:
currentFile.split('/').pop(),
content:
editor.getValue()
}
)
}
);

if(currentFile)
renderLintErrors(
d.errors
);

}catch(e){}
}

function languageKey(path){

const e=
path.split('.')
.pop()
.toLowerCase();

if(
[
'js',
'mjs',
'cjs',
'ts',
'jsx',
'tsx'
].includes(e)
)
return 'javascript';

if(
[
'html',
'htm',
'xml',
'svg'
].includes(e)
)
return 'html';

if(
[
'css',
'scss',
'sass',
'less'
].includes(e)
)
return 'css';

return e;
}

function sendWS(packet){

if(
ws
&&
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

term.focus();

fitTerminal();
};

ws.onmessage=
e=>{

if(
typeof e.data==='string'
&&
e.data.startsWith('{')
){

try{

const control=
JSON.parse(
e.data
);

if(
control.__vstermu
){

handleControl(
control.__vstermu
);

return;
}

}catch(err){}
}

term.write(
e.data
);
};

ws.onclose=
()=>{

$('termState')
.textContent=
'reconnecting';

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

function handleControl(control){

if(
control.action==='env_enable'
)
terminalCommand(
'.env enable'
);

else if(
control.action==='env_unenable'
)
terminalCommand(
'.env unenable'
);

else if(
control.action==='toast'
)
toast(
control.message||''
);
}

window.addEventListener(
'resize',
()=>{
clearTimeout(
window.fitTimer
);

window.fitTimer=
setTimeout(
fitTerminal,
80
);
}
);


async function init(){

try{

await loadStyle();

await loadEnvStatus();

await loadRoots();

const state=
await api(
'/api/state'
);

envEnabled=
!!state.envEnabled;

recentFiles=
Array.isArray(
state.openFiles
)
?
state.openFiles.filter(
path=>
typeof path==='string'
&&
!isIgnoredClient(path)
)
:
[];

renderTabs();

if(
state.lastFile
&&
recentFiles.includes(
state.lastFile
)
){

try{

await openFile(
state.lastFile
);

}catch(e){

recentFiles=
recentFiles.filter(
path=>
path!==state.lastFile
);

renderTabs();
}
}

}catch(e){

toast(
e.message
);

}finally{

void 0;
}

connectTerminal();

setTimeout(
fitTerminal,
120
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
