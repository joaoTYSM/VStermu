# version: 2.3 beta
# @2026 MIT License
# by joao // discord: https://discord.gg/m2Nhbp8TPB tiktok: https://www.tiktok.com/@joao401?_r=1&_t=ZS-9ABZEaF17C1
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
import ast
import shlex
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
ENV_STATE_FILE = os.path.join(SCRIPTS_SAVE, "env.state.json")
MAX_FILE_SIZE = 8 * 1024 * 1024
MAX_SCAN_ITEMS = 3000
ENV_DISABLED_MESSAGE = 'Sorry, but for your protection, this feature is disabled by default. Go to Termux, and in the command tab created when you ran it, there will be a command line ">>>". Type ".env enable".'
PROTECTED_INSTALLER = "vstermu-installer.py"

app = Flask(__name__)
sock = Sock(app)
app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25, "max_message_size": 2 * 1024 * 1024}

DEFAULT_STYLE = {
    "theme": "dark",
    "fontSize": 14,
    "editorFontSize": 14,
    "terminalFontSize": 14,
    "sidebarWidth": 280,
    "terminalHeight": 280,
    "wordWrap": True,
    "envEnabled": False,
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
    "sass": "fa-brands fa-sass",
    "less": "fa-brands fa-less",
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

LANGUAGE_COMMANDS = {
    ".py": ["python"],
    ".pyw": ["python"],
    ".js": ["node"],
    ".mjs": ["node"],
    ".cjs": ["node"],
    ".ts": ["npx", "tsx"],
    ".tsx": ["npx", "tsx"],
    ".jsx": ["node"],
    ".php": ["php"],
    ".rb": ["ruby"],
    ".lua": ["lua"],
    ".pl": ["perl"],
    ".r": ["Rscript"],
    ".go": ["go", "run"],
    ".rs": ["cargo", "run", "--bin"],
    ".java": ["javac"],
    ".c": ["gcc"],
    ".cc": ["g++"],
    ".cpp": ["g++"],
    ".sh": ["bash"],
    ".bash": ["bash"],
    ".zsh": ["zsh"],
    ".fish": ["fish"],
}

LANGUAGE_ALIASES = {
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".less": "css",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".py": "python",
    ".pyw": "python",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".fish": "shell",
    ".json": "json",
    ".xml": "xml",
    ".svg": "xml",
    ".md": "markdown",
    ".sql": "sql",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".php": "php",
}

PYTHON_HINTS = [
    "False", "None", "True", "and", "as", "assert", "async", "await", "break", "case", "class", "continue", "def", "del", "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in", "is", "lambda", "match", "nonlocal", "not", "or", "pass", "raise", "return", "try", "while", "with", "yield", "print", "len", "range", "enumerate", "zip", "map", "filter", "sum", "min", "max", "sorted", "reversed", "isinstance", "issubclass", "type", "id", "open", "input", "str", "int", "float", "bool", "bytes", "bytearray", "list", "tuple", "set", "dict", "object", "super", "property", "staticmethod", "classmethod", "dataclass", "Exception", "ValueError", "TypeError", "RuntimeError", "KeyError", "IndexError", "FileNotFoundError", "Path", "os", "sys", "json", "re", "time", "math", "random", "datetime", "asyncio", "logging", "subprocess", "threading", "typing", "collections", "functools", "itertools", "pathlib", "http", "urllib", "socket", "sqlite3", "hashlib", "secrets", "base64", "uuid", "requests", "flask", "FastAPI", "pydantic", "pytest", "discord", "commands", "tasks", "app_commands", "discord.ext", "Bot", "Client", "Embed", "Intents", "Interaction", "Message", "User", "Member", "Guild", "TextChannel", "VoiceChannel", "Webhook", "File", "ui", "View", "Button", "Select", "Modal", "Cog", "Context", "SlashCommand", "HTTPException", "NotFound", "Forbidden", "aiohttp", "uvicorn", "numpy", "pandas", "PIL", "pygame"
]

JAVASCRIPT_HINTS = [
    "const", "let", "var", "function", "return", "if", "else", "for", "while", "do", "switch", "case", "break", "continue", "try", "catch", "finally", "throw", "new", "class", "extends", "import", "export", "from", "default", "async", "await", "yield", "typeof", "instanceof", "in", "of", "this", "super", "true", "false", "null", "undefined", "NaN", "Infinity", "console", "window", "document", "globalThis", "JSON", "Math", "Date", "Promise", "Map", "Set", "WeakMap", "WeakSet", "Array", "Object", "String", "Number", "Boolean", "RegExp", "Error", "URL", "URLSearchParams", "fetch", "WebSocket", "setTimeout", "setInterval", "clearTimeout", "clearInterval", "require", "module", "process", "Buffer", "fs", "path", "os", "http", "https", "events", "stream", "express", "discord", "Client", "GatewayIntentBits", "Partials", "Collection", "EmbedBuilder", "ActionRowBuilder", "ButtonBuilder", "ButtonStyle", "StringSelectMenuBuilder", "StringSelectMenuOptionBuilder", "ModalBuilder", "TextInputBuilder", "TextInputStyle", "PermissionsBitField", "REST", "Routes", "SlashCommandBuilder", "InteractionType", "Events", "ActivityType", "VoiceChannel", "TextChannel", "Guild", "User", "Message", "ChannelType", "axios", "react", "useState", "useEffect", "useMemo", "useRef", "useCallback", "ReactDOM", "fastify", "koa", "socket", "typescript"
]

CSS_HINTS = [
    "align-content", "align-items", "align-self", "animation", "animation-delay", "animation-direction", "animation-duration", "animation-fill-mode", "animation-iteration-count", "animation-name", "animation-play-state", "animation-timing-function", "appearance", "backdrop-filter", "background", "background-color", "background-image", "background-position", "background-repeat", "background-size", "border", "border-color", "border-radius", "border-width", "box-shadow", "box-sizing", "color", "column-gap", "columns", "cursor", "display", "filter", "flex", "flex-basis", "flex-direction", "flex-flow", "flex-grow", "flex-shrink", "flex-wrap", "font", "font-family", "font-size", "font-weight", "gap", "grid", "grid-area", "grid-template-columns", "grid-template-rows", "height", "justify-content", "left", "line-height", "margin", "max-height", "max-width", "min-height", "min-width", "object-fit", "opacity", "overflow", "padding", "place-content", "place-items", "position", "right", "text-align", "text-decoration", "text-overflow", "top", "transform", "transition", "user-select", "visibility", "white-space", "width", "z-index"
]

HTML_HINTS = [
    "html", "head", "body", "title", "meta", "link", "style", "script", "main", "header", "footer", "nav", "section", "article", "aside", "div", "span", "p", "a", "button", "input", "textarea", "select", "option", "label", "form", "table", "thead", "tbody", "tr", "th", "td", "ul", "ol", "li", "img", "video", "audio", "canvas", "svg", "path", "iframe", "details", "summary", "dialog", "class", "id", "src", "href", "style", "title", "alt", "width", "height", "type", "name", "value", "placeholder", "disabled", "checked", "selected", "aria-label", "role", "data-"
]

LANGUAGE_HINTS = {
    "python": PYTHON_HINTS,
    "javascript": JAVASCRIPT_HINTS,
    "typescript": JAVASCRIPT_HINTS + ["interface", "type", "enum", "namespace", "readonly", "public", "private", "protected", "implements", "declare", "never", "unknown", "any", "void", "keyof", "Partial", "Pick", "Omit", "Record", "PromiseLike"],
    "css": CSS_HINTS,
    "html": HTML_HINTS,
    "shell": ["cd", "pwd", "ls", "cp", "mv", "rm", "mkdir", "rmdir", "touch", "cat", "less", "more", "grep", "find", "sed", "awk", "echo", "printf", "export", "unset", "source", "alias", "which", "type", "chmod", "ps", "kill", "env", "ssh", "curl", "wget", "git", "python", "node", "npm", "npx", "pip", "termux-open", "termux-setup-storage"],
    "json": ["true", "false", "null"],
    "sql": ["SELECT", "FROM", "WHERE", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "JOIN", "LEFT JOIN", "RIGHT JOIN", "INNER JOIN", "GROUP BY", "ORDER BY", "HAVING", "LIMIT", "OFFSET", "AS", "AND", "OR", "NOT", "NULL", "VALUES", "PRIMARY KEY", "FOREIGN KEY", "INDEX", "VIEW", "TRIGGER"],
    "java": ["public", "private", "protected", "class", "interface", "extends", "implements", "static", "final", "void", "int", "long", "double", "float", "boolean", "char", "new", "this", "super", "return", "if", "else", "for", "while", "switch", "try", "catch", "finally", "package", "import", "throws", "throw", "String", "System", "List", "Map", "Set", "Optional"],
    "c": ["include", "define", "ifdef", "ifndef", "endif", "struct", "enum", "typedef", "const", "static", "extern", "inline", "void", "int", "char", "short", "long", "float", "double", "size_t", "uint8_t", "uint16_t", "uint32_t", "uint64_t", "NULL", "printf", "scanf", "malloc", "calloc", "realloc", "free", "memcpy", "memset", "strlen"],
    "cpp": ["include", "namespace", "using", "class", "struct", "public", "private", "protected", "virtual", "override", "final", "template", "typename", "constexpr", "consteval", "constinit", "auto", "decltype", "nullptr", "std", "vector", "string", "unordered_map", "map", "set", "optional", "variant", "unique_ptr", "shared_ptr", "make_unique", "make_shared", "cout", "cin", "endl"],
    "rust": ["fn", "let", "mut", "pub", "impl", "trait", "struct", "enum", "match", "if", "else", "loop", "while", "for", "in", "use", "mod", "crate", "self", "Self", "async", "await", "move", "ref", "const", "static", "type", "where", "Result", "Option", "Some", "None", "Vec", "String", "HashMap", "println!", "format!"],
    "go": ["package", "import", "func", "var", "const", "type", "struct", "interface", "map", "chan", "go", "defer", "select", "switch", "case", "default", "if", "else", "for", "range", "return", "error", "string", "int", "bool", "byte", "rune", "fmt", "context", "http", "json"],
    "php": ["<?php", "echo", "function", "class", "interface", "trait", "extends", "implements", "namespace", "use", "public", "protected", "private", "static", "final", "abstract", "return", "if", "else", "foreach", "while", "match", "array", "string", "int", "float", "bool", "null", "true", "false", "isset", "empty", "json_encode", "json_decode"]
}

LIBRARY_HINTS = {
    "discord.py": ["discord", "discord.ext", "commands", "app_commands", "tasks", "Client", "Bot", "AutoShardedBot", "Intents", "Embed", "Interaction", "Message", "User", "Member", "Guild", "Role", "TextChannel", "VoiceChannel", "Thread", "Webhook", "File", "Attachment", "Permissions", "PermissionOverwrite", "Colour", "Color", "HTTPException", "Forbidden", "NotFound", "ui", "View", "Button", "Select", "Modal", "TextInput", "Cog", "Context", "check", "cooldown", "command", "hybrid_command", "slash_command", "listener", "tree", "setup_hook", "on_ready", "on_message", "on_interaction", "send", "reply", "edit", "delete", "fetch", "create", "add_roles", "remove_roles", "kick", "ban", "timeout", "purge", "history", "wait_for", "change_presence", "load_extension", "unload_extension", "reload_extension"],
    "discord.js": ["discord.js", "Client", "GatewayIntentBits", "Partials", "Collection", "Events", "ActivityType", "EmbedBuilder", "AttachmentBuilder", "ActionRowBuilder", "ButtonBuilder", "ButtonStyle", "StringSelectMenuBuilder", "StringSelectMenuOptionBuilder", "RoleSelectMenuBuilder", "ChannelSelectMenuBuilder", "UserSelectMenuBuilder", "MentionableSelectMenuBuilder", "ModalBuilder", "TextInputBuilder", "TextInputStyle", "StringSelectMenuInteraction", "ChatInputCommandInteraction", "ButtonInteraction", "ModalSubmitInteraction", "REST", "Routes", "SlashCommandBuilder", "PermissionFlagsBits", "PermissionsBitField", "MessageFlags", "ChannelType", "ComponentType", "Attachment", "Message", "User", "Guild", "GuildMember", "TextChannel", "VoiceChannel", "WebhookClient", "GatewayDispatchEvents"],
    "flask": ["Flask", "request", "jsonify", "Response", "redirect", "url_for", "render_template", "abort", "session", "g", "Blueprint", "send_file", "send_from_directory", "make_response", "flash", "current_app", "json", "route", "get", "post", "put", "delete", "before_request", "after_request", "errorhandler"],
    "fastapi": ["FastAPI", "APIRouter", "Request", "Response", "HTTPException", "Depends", "Query", "Path", "Body", "Header", "Cookie", "Form", "File", "UploadFile", "WebSocket", "BackgroundTasks", "status", "Security", "OAuth2PasswordBearer"],
    "express": ["express", "Router", "Request", "Response", "NextFunction", "json", "urlencoded", "static", "listen", "use", "get", "post", "put", "patch", "delete", "all", "param", "send", "status", "redirect", "render", "download", "cookie", "clearCookie"],
    "react": ["React", "ReactDOM", "useState", "useEffect", "useMemo", "useCallback", "useRef", "useReducer", "useContext", "useLayoutEffect", "useId", "useTransition", "useDeferredValue", "memo", "forwardRef", "lazy", "Suspense", "Fragment", "createElement", "createRoot", "StrictMode"],
    "node": ["process", "Buffer", "console", "require", "module", "__dirname", "__filename", "global", "setImmediate", "clearImmediate", "setTimeout", "setInterval", "clearTimeout", "clearInterval", "fetch", "AbortController", "URL", "URLSearchParams", "TextEncoder", "TextDecoder", "EventEmitter", "Readable", "Writable", "Transform", "Duplex", "fs", "path", "os", "crypto", "http", "https", "url", "events", "stream", "util", "child_process", "worker_threads", "readline", "zlib"]
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

def ensure_data_files():
    os.makedirs(SCRIPTS_SAVE, exist_ok=True)
    os.makedirs(STYLE_DIR, exist_ok=True)
    if not os.path.exists(STYLE_FILE):
        atomic_json_write(STYLE_FILE, DEFAULT_STYLE)
    if not os.path.exists(STATE_FILE):
        atomic_json_write(STATE_FILE, {"openFiles": [], "lastFile": None})
    if not os.path.exists(ENV_STATE_FILE):
        atomic_json_write(ENV_STATE_FILE, {"enabled": False})

def env_enabled():
    value = load_json(ENV_STATE_FILE, {"enabled": False})
    return bool(value.get("enabled", False))

def set_env_enabled(value):
    atomic_json_write(ENV_STATE_FILE, {"enabled": bool(value), "updated": time.time()})

def is_env_file(path):
    name = os.path.basename(os.path.realpath(path)).lower()
    return name == ".env" or name.startswith(".env.")

def is_protected_installer(path):
    return os.path.basename(os.path.realpath(path)) == PROTECTED_INSTALLER

def redact_env_content(content):
    lines = []
    for line in content.splitlines(True):
        newline = "\n" if line.endswith("\n") else ""
        core = line[:-1] if newline else line
        if re.match(r"^\s*(?:export\s+)?[^#=\s]+\s*=", core):
            prefix = re.match(r"^(\s*(?:export\s+)?[^#=\s]+\s*=)", core).group(1)
            lines.append(prefix + " <hidden>" + newline)
        else:
            lines.append(line)
    return "".join(lines)

def roots():
    result = [{"name": "Termux Home", "path": HOME, "kind": "home"}]
    if os.path.isdir(SHARED):
        result.append({"name": "Shared Storage", "path": os.path.realpath(SHARED), "kind": "shared"})
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
            if entry.name == PROTECTED_INSTALLER:
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                stat = entry.stat(follow_symlinks=False)
                entries.append({
                    "name": entry.name,
                    "path": entry.path,
                    "type": "directory" if is_dir else "file",
                    "icon": file_icon(entry.name, is_dir),
                    "size": stat.st_size if not is_dir else 0,
                    "mtime": stat.st_mtime,
                    "hidden": entry.name.startswith("."),
                    "symlink": entry.is_symlink(),
                    "protected": is_env_file(entry.path),
                })
            except (PermissionError, FileNotFoundError, OSError):
                continue
    entries.sort(key=lambda x: (x["type"] != "directory", x["name"].lower()))
    return entries

def is_probably_text(path):
    ext = Path(path).suffix.lower()
    text_ext = {
        ".txt", ".md", ".json", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css", ".scss", ".sass", ".less",
        ".py", ".pyw", ".sh", ".bash", ".zsh", ".fish", ".php", ".java", ".c", ".cc", ".cpp", ".h", ".hpp", ".rs", ".go", ".sql",
        ".xml", ".svg", ".yaml", ".yml", ".toml", ".ini", ".conf", ".cfg", ".env", ".lock", ".log", ".rb", ".lua", ".pl", ".r"
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

def shell_quote(value):
    return shlex.quote(value)

def safe_relative_or_absolute(path):
    path = safe_path(path)
    try:
        rel = os.path.relpath(path, HOME)
        if rel == ".":
            return "."
        if not rel.startswith(".."):
            return rel
    except Exception:
        pass
    return path

def command_for_file(path):
    real = safe_path(path)
    ext = Path(real).suffix.lower()
    rel = safe_relative_or_absolute(real)
    if ext in {".py", ".pyw"}:
        return f"python {shell_quote(rel)}"
    if ext in {".js", ".mjs", ".cjs", ".jsx"}:
        return f"node {shell_quote(rel)}"
    if ext in {".ts", ".tsx"}:
        return f"npx --yes tsx {shell_quote(rel)}"
    if ext == ".php":
        return f"php {shell_quote(rel)}"
    if ext == ".rb":
        return f"ruby {shell_quote(rel)}"
    if ext == ".lua":
        return f"lua {shell_quote(rel)}"
    if ext in {".pl"}:
        return f"perl {shell_quote(rel)}"
    if ext in {".sh", ".bash"}:
        return f"bash {shell_quote(rel)}"
    if ext == ".zsh":
        return f"zsh {shell_quote(rel)}"
    if ext == ".fish":
        return f"fish {shell_quote(rel)}"
    if ext == ".go":
        return f"go run {shell_quote(rel)}"
    if ext == ".rs":
        return f"rustc {shell_quote(rel)} && ./main"
    if ext in {".c", ".cc", ".cpp"}:
        compiler = "g++" if ext in {".cc", ".cpp"} else "gcc"
        return f"{compiler} {shell_quote(rel)} -o /tmp/vstermu-run && /tmp/vstermu-run"
    if ext == ".java":
        return f"javac {shell_quote(rel)} && java {shell_quote(Path(rel).stem)}"
    if ext in {".html", ".htm"}:
        return f"termux-open {shell_quote('file://' + real)}"
    return f"echo No direct run command is configured for {shell_quote(os.path.basename(real))}"

@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")

@app.get("/api/roots")
def api_roots():
    return jsonify({"roots": roots(), "home": HOME, "shared": SHARED})

@app.get("/api/list")
def api_list():
    try:
        path = safe_path(request.args.get("path", HOME))
        return jsonify({"path": path, "label": rel_label(path), "entries": list_directory(path)})
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except FileNotFoundError:
        return jsonify({"error": "Directory not found"}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.get("/api/read")
def api_read():
    try:
        path = safe_path(request.args.get("path", ""))
        if is_protected_installer(path):
            return jsonify({"error": "Protected file"}), 403
        if not os.path.isfile(path):
            return jsonify({"error": "File not found"}), 404
        size = os.path.getsize(path)
        if size > MAX_FILE_SIZE:
            return jsonify({"error": f"File is larger than {MAX_FILE_SIZE // 1024 // 1024} MB"}), 413
        if not is_probably_text(path):
            return jsonify({"error": "Binary files are not opened in the editor"}), 415
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()
        protected = is_env_file(path)
        if protected and not env_enabled():
            content = redact_env_content(content)
            return jsonify({
                "path": path,
                "content": content,
                "size": size,
                "mtime": os.path.getmtime(path),
                "protected": True,
                "envEnabled": False,
                "message": ENV_DISABLED_MESSAGE
            })
        return jsonify({
            "path": path,
            "content": content,
            "size": size,
            "mtime": os.path.getmtime(path),
            "protected": protected,
            "envEnabled": env_enabled()
        })
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.put("/api/write")
def api_write():
    try:
        payload = request.get_json(force=True) or {}
        path = safe_path(payload.get("path", ""))
        if is_protected_installer(path):
            return jsonify({"error": "Protected file"}), 403
        if is_env_file(path) and not env_enabled():
            return jsonify({"error": ENV_DISABLED_MESSAGE}), 403
        content = payload.get("content", "")
        if not isinstance(content, str):
            return jsonify({"error": "Content must be text"}), 400
        data = content.encode("utf-8")
        if len(data) > MAX_FILE_SIZE:
            return jsonify({"error": "File is too large"}), 413
        atomic_write(path, data)
        return jsonify({"ok": True, "path": path, "size": len(data), "mtime": os.path.getmtime(path)})
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.post("/api/create")
def api_create():
    try:
        payload = request.get_json(force=True) or {}
        parent = safe_path(payload.get("parent", HOME))
        name = str(payload.get("name", "")).strip()
        kind = payload.get("type", "file")
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            return jsonify({"error": "Invalid name"}), 400
        if name == PROTECTED_INSTALLER:
            return jsonify({"error": "Protected filename"}), 403
        target = safe_path(os.path.join(parent, name))
        if os.path.exists(target):
            return jsonify({"error": "Already exists"}), 409
        if kind == "directory":
            os.makedirs(target)
        else:
            atomic_write(target, b"")
        return jsonify({"ok": True, "path": target})
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.post("/api/rename")
def api_rename():
    try:
        payload = request.get_json(force=True) or {}
        source = safe_path(payload.get("path", ""))
        name = str(payload.get("name", "")).strip()
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            return jsonify({"error": "Invalid name"}), 400
        if is_protected_installer(source) or name == PROTECTED_INSTALLER:
            return jsonify({"error": "Protected file"}), 403
        target = safe_path(os.path.join(os.path.dirname(source), name))
        if os.path.exists(target):
            return jsonify({"error": "A file or folder with that name already exists"}), 409
        os.rename(source, target)
        return jsonify({"ok": True, "path": target})
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.post("/api/delete")
def api_delete():
    try:
        payload = request.get_json(force=True) or {}
        path = safe_path(payload.get("path", ""))
        if path in {HOME, os.path.realpath(SHARED), DATA_ROOT}:
            return jsonify({"error": "Protected path"}), 403
        if is_protected_installer(path):
            return jsonify({"error": "Protected file"}), 403
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
        else:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"ok": True})
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.get("/api/style")
def api_style():
    style = dict(DEFAULT_STYLE)
    style.update(load_json(STYLE_FILE, {}))
    style["envEnabled"] = env_enabled()
    return jsonify(style)

@app.put("/api/style")
def api_style_write():
    payload = request.get_json(force=True) or {}
    style = dict(DEFAULT_STYLE)
    style.update({k: v for k, v in payload.items() if k in DEFAULT_STYLE and k != "envEnabled"})
    atomic_json_write(STYLE_FILE, style)
    return jsonify({**style, "envEnabled": env_enabled()})

@app.get("/api/state")
def api_state():
    state = load_json(STATE_FILE, {"openFiles": [], "lastFile": None})
    files = []
    for item in state.get("openFiles", []):
        try:
            p = safe_path(item)
            if not is_protected_installer(p):
                files.append(p)
        except Exception:
            continue
    last = state.get("lastFile")
    try:
        if last:
            last = safe_path(last)
            if is_protected_installer(last):
                last = None
    except Exception:
        last = None
    return jsonify({"openFiles": files[:20], "lastFile": last})

@app.put("/api/state")
def api_state_write():
    payload = request.get_json(force=True) or {}
    files = []
    for item in payload.get("openFiles", []):
        try:
            p = safe_path(item)
            if not is_protected_installer(p):
                files.append(p)
        except Exception:
            continue
    last = payload.get("lastFile")
    try:
        if last:
            last = safe_path(last)
            if is_protected_installer(last):
                last = None
    except Exception:
        last = None
    state = {"openFiles": list(dict.fromkeys(files))[-20:], "lastFile": last}
    atomic_json_write(STATE_FILE, state)
    return jsonify(state)

@app.get("/api/env")
def api_env():
    return jsonify({"enabled": env_enabled(), "message": ENV_DISABLED_MESSAGE})

@app.put("/api/env")
def api_env_write():
    payload = request.get_json(force=True) or {}
    enabled = bool(payload.get("enabled", False))
    set_env_enabled(enabled)
    return jsonify({"enabled": enabled, "message": ENV_DISABLED_MESSAGE})

@app.get("/api/info")
def api_info():
    return jsonify({
        "app": APP_NAME,
        "home": HOME,
        "shared": SHARED,
        "data": DATA_ROOT,
        "python": os.sys.version,
        "platform": os.uname().sysname,
        "cwd": os.getcwd(),
        "envEnabled": env_enabled()
    })

def lint_python(code):
    try:
        ast.parse(code)
        return []
    except SyntaxError as exc:
        line = max(1, exc.lineno or 1)
        col = max(0, (exc.offset or 1) - 1)
        return [{
            "line": line - 1,
            "start": col,
            "end": col + 1,
            "message": exc.msg or "Syntax error",
            "severity": "error"
        }]

def lint_json(code):
    try:
        json.loads(code)
        return []
    except json.JSONDecodeError as exc:
        line = max(1, exc.lineno or 1)
        col = max(0, exc.colno - 1)
        return [{
            "line": line - 1,
            "start": col,
            "end": col + 1,
            "message": exc.msg or "Invalid JSON",
            "severity": "error"
        }]

def lint_shell(code):
    try:
        result = subprocess.run(
            ["bash", "-n"],
            input=code,
            text=True,
            capture_output=True,
            timeout=2
        )
        if result.returncode == 0:
            return []
        message = (result.stderr.strip().splitlines() or ["Shell syntax error"])[-1]
        line = 0
        match = re.search(r": line (\d+):", result.stderr)
        if match:
            line = max(0, int(match.group(1)) - 1)
        return [{
            "line": line,
            "start": 0,
            "end": max(1, len(code.splitlines()[line]) if code.splitlines() else 1),
            "message": message,
            "severity": "error"
        }]
    except Exception:
        return []

def generic_balance_lint(code, language):
    errors = []
    pairs = {"{": "}", "[": "]", "(": ")"}
    closing = {v: k for k, v in pairs.items()}
    stack = []
    quote = None
    escaped = False
    line = 0
    col = 0

    for char in code:
        if char == "\n":
            line += 1
            col = 0
            continue

        if escaped:
            escaped = False
            col += 1
            continue

        if quote:
            if char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            col += 1
            continue

        if char in {'"', "'", "`"} and language in {"javascript", "typescript", "python", "css", "c", "cpp", "java", "go", "rust", "php"}:
            quote = char
            col += 1
            continue

        if char in pairs:
            stack.append((char, line, col))
        elif char in closing:
            if not stack or stack[-1][0] != closing[char]:
                errors.append({
                    "line": line,
                    "start": col,
                    "end": col + 1,
                    "message": f"Unexpected {char}",
                    "severity": "error"
                })
            else:
                stack.pop()

        col += 1

    if stack:
        char, line, col = stack[-1]
        errors.append({
            "line": line,
            "start": col,
            "end": col + 1,
            "message": f"Unclosed {char}",
            "severity": "error"
        })

    return errors[:20]

@app.post("/api/lint")
def api_lint():
    try:
        payload = request.get_json(force=True) or {}
        path = safe_path(payload.get("path", ""))
        code = payload.get("content", "")

        if not isinstance(code, str):
            return jsonify({"annotations": []})

        ext = Path(path).suffix.lower()

        if ext in {".py", ".pyw"}:
            annotations = lint_python(code)

        elif ext == ".json":
            annotations = lint_json(code)

        elif ext in {".sh", ".bash"}:
            annotations = lint_shell(code)

        elif ext in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}:
            annotations = generic_balance_lint(code, "javascript")

        elif ext in {".css", ".scss", ".sass", ".less", ".c", ".cc", ".cpp", ".h", ".hpp", ".java", ".go", ".rs", ".php"}:
            annotations = generic_balance_lint(code, LANGUAGE_ALIASES.get(ext, "text"))

        elif ext in {".html", ".htm", ".xml", ".svg"}:
            annotations = generic_balance_lint(code, "html")
            tags = re.findall(r"<\s*(/?)\s*([a-zA-Z][\w:-]*)[^>]*?>", code)
            stack = []
            void = {
                "area", "base", "br", "col", "embed", "hr", "img",
                "input", "link", "meta", "param", "source", "track", "wbr"
            }
            offset_lines = code.splitlines()

            for line_index, line_text in enumerate(offset_lines):
                for match in re.finditer(r"<\s*(/?)\s*([a-zA-Z][\w:-]*)[^>]*?>", line_text):
                    closing_tag, tag = match.group(1), match.group(2).lower()

                    if tag in void:
                        continue

                    if closing_tag:
                        if stack and stack[-1][0] == tag:
                            stack.pop()
                        else:
                            annotations.append({
                                "line": line_index,
                                "start": match.start(),
                                "end": match.end(),
                                "message": f"Unexpected closing tag </{tag}>",
                                "severity": "error"
                            })
                    else:
                        stack.append((tag, line_index, match.start()))

            for tag, line_index, start in reversed(stack[-10:]):
                annotations.append({
                    "line": line_index,
                    "start": start,
                    "end": min(len(offset_lines[line_index]), start + len(tag) + 2),
                    "message": f"Unclosed tag <{tag}>",
                    "severity": "error"
                })

        else:
            annotations = generic_balance_lint(code, "text")

        return jsonify({"annotations": annotations[:30]})

    except Exception as exc:
        return jsonify({"annotations": [], "error": str(exc)})

@app.post("/api/execute")
def api_execute():
    try:
        payload = request.get_json(force=True) or {}
        path = safe_path(payload.get("path", ""))

        if is_protected_installer(path):
            return jsonify({"error": "Protected file"}), 403

        if is_env_file(path) and not env_enabled():
            return jsonify({"error": ENV_DISABLED_MESSAGE}), 403

        if not os.path.isfile(path):
            return jsonify({"error": "File not found"}), 404

        command = command_for_file(path)

        return jsonify({
            "ok": True,
            "command": command,
            "cwd": os.path.dirname(path),
            "path": path
        })

    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.post("/api/live")
def api_live():
    try:
        payload = request.get_json(force=True) or {}
        path = safe_path(payload.get("path", ""))
        code = payload.get("content", "")

        if not isinstance(code, str):
            return jsonify({"error": "Content must be text"}), 400

        ext = Path(path).suffix.lower()

        if ext in {".py", ".pyw"}:
            command = ["python", "-c", code]
        elif ext in {".js", ".mjs", ".cjs"}:
            command = ["node", "-e", code]
        elif ext == ".php":
            command = ["php", "-r", code]
        elif ext == ".rb":
            command = ["ruby", "-e", code]
        elif ext == ".lua":
            command = ["lua", "-e", code]
        elif ext in {".sh", ".bash"}:
            command = ["bash", "-lc", code]
        else:
            return jsonify({
                "ok": True,
                "mode": "static",
                "output": "",
                "error": ""
            })

        process = subprocess.run(
            command,
            cwd=os.path.dirname(path),
            capture_output=True,
            text=True,
            timeout=3,
            env=os.environ.copy()
        )

        return jsonify({
            "ok": process.returncode == 0,
            "mode": "execute",
            "output": process.stdout[-12000:],
            "error": process.stderr[-12000:],
            "returncode": process.returncode
        })

    except subprocess.TimeoutExpired:
        return jsonify({
            "ok": False,
            "mode": "execute",
            "output": "",
            "error": "Live execution timed out after 3 seconds",
            "returncode": -1
        })

    except FileNotFoundError as exc:
        return jsonify({
            "ok": False,
            "mode": "execute",
            "output": "",
            "error": f"Runtime not found: {exc}",
            "returncode": -1
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "mode": "execute",
            "output": "",
            "error": str(exc),
            "returncode": -1
        })

@app.get("/api/hints")
def api_hints():
    language = request.args.get("language", "")
    installed = []

    if language == "python":
        try:
            import pkgutil
            installed = [m.name for m in pkgutil.iter_modules()]
        except Exception:
            installed = []

    elif language in {"javascript", "typescript"}:
        candidates = []

        for base in [
            os.path.join(HOME, "node_modules"),
            os.path.join(os.getcwd(), "node_modules")
        ]:
            if os.path.isdir(base):
                try:
                    candidates.extend(
                        name
                        for name in os.listdir(base)
                        if name.startswith("@") or re.match(r"^[A-Za-z0-9._-]+$", name)
                    )
                except OSError:
                    pass

        installed = sorted(set(candidates))[:3000]

    hints = set(LANGUAGE_HINTS.get(language, []))

    for key, values in LIBRARY_HINTS.items():
        hints.add(key)
        hints.update(values)

    hints.update(installed)

    return jsonify({
        "language": language,
        "items": sorted(hints)[:5000]
    })

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
        env.update({
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "TERM_PROGRAM": "VStermu-x",
            "LANG": env.get("LANG", "C.UTF-8")
        })

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
            cols = max(20, min(500, int(cols)))
            rows = max(5, min(300, int(rows)))

            packed = struct.pack(
                "HHHH",
                rows,
                cols,
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

        except (
            OSError,
            ValueError,
            TypeError
        ):
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
                    session.write(
                        "cd -- "
                        + shell_quote(path)
                        + "\n"
                    )

            elif kind == "env_echo":
                session.send(
                    packet.get(
                        "text",
                        ""
                    )
                )

    except Exception:
        pass

    finally:
        session.close()

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
:root{--bg:#0b0d10;--panel:#111418;--panel2:#15191e;--border:#252b32;--text:#e7eaf0;--muted:#858d99;--accent:#55d98b;--accent2:#35a86b;--danger:#ff6262;--blue:#63a4ff;--shadow:0 18px 50px #0008;--sidebar:280px;--term:280px;--editor-size:14px;--radius:10px}
[data-theme=light]{--bg:#f5f6f8;--panel:#fff;--panel2:#f0f2f5;--border:#d9dde4;--text:#16191e;--muted:#69717d;--accent:#15803d;--accent2:#166534;--danger:#dc2626;--blue:#2563eb}
[data-theme=dracula]{--bg:#282a36;--panel:#21222c;--panel2:#191a21;--border:#44475a;--text:#f8f8f2;--muted:#8b91ad;--accent:#50fa7b;--accent2:#37d35e;--danger:#ff5555;--blue:#8be9fd}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%;margin:0;overflow:hidden}
body{font-family:Inter,sans-serif;background:var(--bg);color:var(--text);font-size:14px}
button,input,select{font:inherit;color:inherit}
button{border:0;background:none}
#app{height:100%;display:grid;grid-template-rows:52px 1fr}
.topbar{height:52px;background:var(--panel);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 12px;z-index:30}
.brand{display:flex;align-items:center;gap:9px;font-weight:700;white-space:nowrap}
.brand img{width:27px;height:27px}
.top-actions{display:flex;align-items:center;gap:5px}
.icon-btn,.top-btn{height:34px;min-width:34px;padding:0 9px;border:1px solid var(--border);border-radius:8px;background:var(--panel2);cursor:pointer}
.icon-btn:active,.top-btn:active{transform:scale(.97)}
.top-btn{display:flex;gap:7px;align-items:center}
.workspace{min-height:0;display:grid;grid-template-columns:var(--sidebar) minmax(0,1fr);position:relative}
.sidebar{background:var(--panel);border-right:1px solid var(--border);min-width:0;display:flex;flex-direction:column;z-index:20}
.sidebar-head{height:42px;display:flex;align-items:center;justify-content:space-between;padding:0 10px;border-bottom:1px solid var(--border)}
.section-title{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700}
.sidebar-tools{display:flex;gap:2px}
.small-btn{width:30px;height:30px;border-radius:7px;color:var(--muted);cursor:pointer}
.small-btn:hover{background:var(--panel2);color:var(--text)}
.small-btn.active{background:var(--panel2);color:var(--accent)}
.roots{border-bottom:1px solid var(--border);padding:5px}
.root{height:31px;border-radius:6px;display:flex;align-items:center;gap:8px;padding:0 8px;color:var(--muted);cursor:pointer;font-size:12px}
.root.active,.root:hover{background:var(--panel2);color:var(--text)}
.tree{flex:1;overflow:auto;padding:5px 4px 60px}
.tree-row{height:32px;display:flex;align-items:center;gap:7px;border-radius:6px;cursor:pointer;padding-right:5px;user-select:none;position:relative}
.tree-row:hover{background:var(--panel2)}
.tree-row.selected{background:#ffffff0d;box-shadow:inset 2px 0 var(--accent)}
.tree-row .arrow{width:14px;text-align:center;color:var(--muted);font-size:10px}
.tree-row .name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.tree-row .meta{font-size:9px;color:var(--muted)}
.tree-row i.file-icon{width:17px;text-align:center;color:#9da7b5}
.tree-row.dir i.file-icon{color:#e3b765}
.tree-empty{padding:20px;color:var(--muted);font-size:12px;text-align:center}
.main{min-width:0;min-height:0;display:flex;flex-direction:column;position:relative}
.editor{min-width:0;min-height:120px;display:flex;flex-direction:column;background:var(--bg);flex:1}
.tabs{height:39px;display:flex;align-items:center;background:var(--panel);border-bottom:1px solid var(--border);overflow:auto;flex-shrink:0}
.tab{height:39px;display:flex;align-items:center;gap:8px;padding:0 12px;border-right:1px solid var(--border);color:var(--muted);font-size:12px;white-space:nowrap;cursor:pointer;position:relative;flex-shrink:0}
.tab.active{color:var(--text);background:var(--bg)}
.tab.unsaved .tab-name::after{content:" •";color:var(--accent)}
.tab-close{font-size:11px;color:var(--muted);margin-left:2px}
.editor-tools{margin-left:auto;display:flex;gap:2px;padding:0 4px;position:sticky;right:0;background:var(--panel);z-index:5}
.editor-wrap{position:relative;flex:1;min-height:0}
.CodeMirror{height:100%;font-family:'Fira Code',monospace;font-size:var(--editor-size);line-height:1.55}
.CodeMirror-gutters{background:var(--panel)!important;border-right:1px solid var(--border)!important}
.CodeMirror-linenumber{color:#68717c}
.CodeMirror-hints{font-family:'Fira Code',monospace;font-size:12px;max-height:280px;z-index:500}
.CodeMirror-lint-marker-error{background-image:none!important;width:16px;height:16px;position:relative}
.CodeMirror-lint-marker-error:after{content:"";position:absolute;left:3px;top:5px;width:9px;height:6px;border-bottom:2px solid var(--danger);transform:rotate(-2deg)}
.cm-manual-error{background:rgba(255,98,98,.18);border-bottom:2px wavy var(--danger)}
.empty-editor{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;color:var(--muted);gap:10px;z-index:2;background:var(--bg)}
.empty-editor img{width:55px;opacity:.6}
.empty-editor b{color:var(--text);font-size:15px}
.hidden{display:none!important}
.live-panel{height:0;min-height:0;display:flex;flex-direction:column;background:var(--panel);border-top:1px solid var(--border);overflow:hidden;transition:height .18s ease;position:relative}
.live-panel.open{height:230px;min-height:140px}
.live-head{height:34px;display:flex;align-items:center;padding:0 8px;border-bottom:1px solid var(--border);flex-shrink:0}
.live-title{display:flex;align-items:center;gap:7px;font-size:11px;color:var(--muted)}
.live-title strong{color:var(--text);font-weight:600}
.live-body{position:relative;flex:1;min-height:0;background:#090b0d;overflow:hidden}
.live-frame{width:100%;height:100%;border:0;background:#fff}
.live-output{height:100%;overflow:auto;padding:10px;font:12px/1.5 'Fira Code',monospace;white-space:pre-wrap;color:#e4e7eb}
.live-placeholder{padding:14px;font-size:12px;color:var(--muted)}
.live-close{margin-left:auto}
.terminal{height:var(--term);min-height:34px;max-height:80vh;background:#070909;color:#dce8df;border-top:1px solid var(--border);display:flex;flex-direction:column;position:relative;flex-shrink:0}
.terminal.minimized{height:34px;min-height:34px}
.term-resizer{height:8px;position:absolute;left:0;right:0;top:-4px;cursor:ns-resize;z-index:10;touch-action:none}
.term-resizer:after{content:"";position:absolute;left:50%;top:3px;transform:translateX(-50%);width:44px;height:2px;border-radius:3px;background:var(--border)}
.term-head{height:34px;background:var(--panel);display:flex;align-items:center;padding:0 8px;border-bottom:1px solid var(--border);flex-shrink:0}
.term-title{display:flex;align-items:center;gap:7px;font-size:11px;color:var(--muted)}
.term-actions{margin-left:auto;display:flex;gap:2px}
.xterm{height:100%;padding:7px 9px}
.xterm .xterm-viewport{background:#070909!important}
.terminal-body{min-height:0;flex:1}
.overlay{position:fixed;inset:0;background:#0007;backdrop-filter:blur(4px);z-index:100;display:none;align-items:center;justify-content:center;padding:15px}
.overlay.open{display:flex}
.modal{width:min(470px,100%);max-height:90vh;overflow:auto;background:var(--panel);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow)}
.modal-head{padding:15px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.modal-title{font-weight:700}
.modal-body{padding:16px}
.modal-row{display:flex;flex-direction:column;gap:6px;margin-bottom:14px}
.modal-row label{font-size:11px;color:var(--muted)}
.modal-row input,.modal-row select{width:100%;height:39px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:0 11px;outline:0}
.modal-row input:focus,.modal-row select:focus{border-color:var(--accent)}
.modal-row.switch-row{flex-direction:row;align-items:center;justify-content:space-between}
.toggle{width:44px;height:25px;border-radius:99px;background:var(--panel2);border:1px solid var(--border);padding:2px;cursor:pointer}
.toggle span{display:block;width:19px;height:19px;border-radius:50%;background:var(--muted);transition:.15s}
.toggle.on{background:var(--accent2);border-color:var(--accent2)}
.toggle.on span{transform:translateX(19px);background:#fff}
.modal-note{font-size:12px;line-height:1.5;color:var(--muted);background:var(--panel2);border:1px solid var(--border);padding:10px;border-radius:8px;margin-bottom:14px}
.modal-foot{display:flex;justify-content:flex-end;gap:8px;padding:12px 16px;border-top:1px solid var(--border)}
.btn{height:36px;border-radius:8px;padding:0 13px;background:var(--panel2);border:1px solid var(--border);cursor:pointer}
.btn.primary{background:var(--accent2);border-color:var(--accent2);color:#fff}
.btn.danger{color:#fff;background:var(--danger);border-color:var(--danger)}
.context{position:fixed;z-index:200;width:235px;background:var(--panel);border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow);padding:6px;display:none}
.context.open{display:block}
.context button{width:100%;height:37px;border-radius:7px;display:flex;align-items:center;gap:10px;padding:0 10px;text-align:left;cursor:pointer}
.context button:hover{background:var(--panel2)}
.context button.danger{color:var(--danger)}
.context hr{border:0;border-top:1px solid var(--border);margin:5px 0}
.toast{position:fixed;left:50%;bottom:18px;transform:translate(-50%,20px);background:var(--panel);border:1px solid var(--border);box-shadow:var(--shadow);padding:10px 14px;border-radius:9px;color:var(--text);font-size:12px;opacity:0;pointer-events:none;transition:.2s;z-index:300}
.toast.show{opacity:1;transform:translate(-50%,0)}
.backdrop{display:none;position:fixed;inset:0;background:#0006;z-index:15}
.backdrop.show{display:block}
.loading{position:absolute;right:15px;top:12px;font-size:10px;color:var(--muted)}
.run-label{max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@media(max-width:800px){
#app{grid-template-rows:48px 1fr}.topbar{height:48px;padding:0 8px}.brand{font-size:14px}.brand img{width:24px;height:24px}.top-btn span{display:none}.top-btn{padding:0;width:34px;justify-content:center}.workspace{grid-template-columns:1fr}.sidebar{position:absolute;left:0;top:0;bottom:0;width:min(86vw,310px);transform:translateX(-102%);transition:transform .2s;box-shadow:var(--shadow);z-index:20}.sidebar.open{transform:translateX(0)}.tabs{height:36px}.tab{height:36px;padding:0 9px}.editor-tools{padding-right:3px}.main{min-width:0}.live-panel.open{height:210px}.terminal{max-height:76vh}.tree-row{height:38px}.root{height:36px}.context{width:min(260px,calc(100vw - 20px))}.modal{border-radius:13px}.xterm{padding:4px}
}
</style>
</head>
<body>
<div id="app">
<header class="topbar">
<div class="brand"><img src="https://raw.githubusercontent.com/joaoTYSM/VStermu/refs/heads/main/icon.svg"><span>VStermu-x</span></div>
<div class="top-actions">
<button class="icon-btn" id="menuBtn" title="Explorer"><i class="fa-solid fa-bars"></i></button>
<button class="icon-btn" id="saveBtn" title="Save"><i class="fa-solid fa-floppy-disk"></i></button>
<button class="icon-btn" id="settingsBtn" title="Settings"><i class="fa-solid fa-gear"></i></button>
</div>
</header>
<div class="workspace">
<aside class="sidebar" id="sidebar">
<div class="sidebar-head"><span class="section-title">Explorer</span><div class="sidebar-tools"><button class="small-btn" id="newFileBtn" title="New file"><i class="fa-solid fa-file-circle-plus"></i></button><button class="small-btn" id="newFolderBtn" title="New folder"><i class="fa-solid fa-folder-plus"></i></button><button class="small-btn" id="refreshBtn" title="Refresh"><i class="fa-solid fa-rotate"></i></button></div></div>
<div class="roots" id="roots"></div>
<div class="tree" id="tree"><div class="tree-empty">Loading filesystem...</div></div>
</aside>
<div class="backdrop" id="backdrop"></div>
<main class="main" id="mainPanel">
<section class="editor">
<div class="tabs" id="tabs">
<div class="tab"><i class="fa-solid fa-code"></i><span>No file open</span></div>
<div class="editor-tools">
<button class="small-btn" id="runBtn" title="Execute"><i class="fa-solid fa-play"></i></button>
<button class="small-btn" id="liveBtn" title="Live Code"><i class="fa-solid fa-bolt"></i></button>
<button class="small-btn" id="fileConfigBtn" title="File settings"><i class="fa-solid fa-sliders"></i></button>
</div>
</div>
<div class="editor-wrap">
<textarea id="editor"></textarea>
<div class="empty-editor" id="emptyEditor"><img src="https://raw.githubusercontent.com/joaoTYSM/VStermu/refs/heads/main/icon.svg"><b>Select a file to edit</b><span>Files are loaded only when opened.</span></div>
<span class="loading hidden" id="editorLoading">Loading...</span>
</div>
</section>
<section class="live-panel" id="livePanel">
<div class="live-head"><div class="live-title"><i class="fa-solid fa-bolt"></i><span>Live Code</span><strong id="liveLanguage"></strong></div><button class="small-btn live-close" id="liveClose" title="Close"><i class="fa-solid fa-xmark"></i></button></div>
<div class="live-body" id="liveBody"><div class="live-placeholder" id="livePlaceholder">Enable Live Code to preview the current file.</div><iframe class="live-frame hidden" id="liveFrame" sandbox="allow-scripts allow-forms allow-modals allow-popups"></iframe><pre class="live-output hidden" id="liveOutput"></pre></div>
</section>
<section class="terminal" id="terminalPanel">
<div class="term-resizer" id="terminalResizer"></div>
<div class="term-head"><div class="term-title"><i class="fa-solid fa-terminal"></i><span>Termux terminal</span><span id="termState">connecting</span></div><div class="term-actions"><button class="small-btn" id="clearTermBtn" title="Clear"><i class="fa-solid fa-broom"></i></button><button class="small-btn" id="minTermBtn" title="Minimize"><i class="fa-solid fa-chevron-down"></i></button></div></div>
<div class="terminal-body" id="terminalBody"></div>
</section>
</main>
</div>
</div>
<div class="context" id="contextMenu">
<button data-action="open"><i class="fa-solid fa-pen-to-square"></i>Open</button>
<button data-action="rename"><i class="fa-solid fa-i-cursor"></i>Rename</button>
<button data-action="file"><i class="fa-solid fa-file-circle-plus"></i>Add file</button>
<button data-action="folder"><i class="fa-solid fa-folder-plus"></i>Add folder</button>
<button data-action="terminal"><i class="fa-solid fa-terminal"></i>Open terminal here</button>
<hr><button data-action="delete" class="danger"><i class="fa-solid fa-trash"></i>Delete</button>
</div>
<div class="overlay" id="modalOverlay">
<div class="modal">
<div class="modal-head"><span class="modal-title" id="modalTitle">Action</span><button class="small-btn" id="modalClose"><i class="fa-solid fa-xmark"></i></button></div>
<div class="modal-body" id="modalBody"></div>
<div class="modal-foot"><button class="btn" id="modalCancel">Cancel</button><button class="btn primary" id="modalConfirm">Confirm</button></div>
</div>
</div>
<div class="toast" id="toast"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/codemirror.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/javascript/javascript.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/xml/xml.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/css/css.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/htmlmixed/htmlmixed.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/python/python.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/shell/shell.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/markdown/markdown.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/mode/clike/clike.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/edit/closebrackets.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/edit/matchbrackets.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/hint/show-hint.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/hint/anyword-hint.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/hint/javascript-hint.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/hint/css-hint.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/hint/html-hint.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/hint/xml-hint.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/hint/sql-hint.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.20/addon/lint/lint.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js"></script>
<script>
const $=id=>document.getElementById(id);
const api=(url,options={})=>fetch(url,{headers:{'Content-Type':'application/json'},...options}).then(async r=>{const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||`HTTP ${r.status}`);return d});
let style={};
let roots=[];
let currentRoot=null;
let openDirs=new Set();
let selectedPath=null;
let selectedType=null;
let currentFile=null;
let currentParent=null;
let saveTimer=null;
let lintTimer=null;
let liveTimer=null;
let longTimer=null;
let longTriggered=false;
let modalAction=null;
let recentFiles=[];
let lintMarks=[];
let liveEnabled=false;
let terminalLineCapture="";
let envCaptureMode=false;
let envStatus=false;
let terminalResizePointer=null;

const editor=CodeMirror.fromTextArea($('editor'),{lineNumbers:true,theme:'material-darker',mode:'javascript',indentUnit:4,tabSize:4,lineWrapping:true,viewportMargin:40,matchBrackets:true,autoCloseBrackets:true,extraKeys:{'Ctrl-S':()=>saveFile(),'Cmd-S':()=>saveFile(),'Ctrl-Space':cm=>showAutocomplete(cm)}});
const term=new Terminal({cursorBlink:true,convertEol:true,scrollback:5000,fontFamily:'Fira Code,monospace',fontSize:14,theme:{background:'#070909',foreground:'#dce8df',cursor:'#55d98b',selectionBackground:'#28553b'}});
const fitAddon=new FitAddon.FitAddon();
term.loadAddon(fitAddon);
term.open($('terminalBody'));

function toast(message){$('toast').textContent=message;$('toast').classList.add('show');clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>$('toast').classList.remove('show'),2400)}
function icon(name){return `<i class="${name}"></i>`}
function escapeHtml(s){return String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function formatSize(n){if(n<1024)return n+' B';if(n<1048576)return (n/1024).toFixed(1)+' KB';return (n/1048576).toFixed(1)+' MB'}
function extOf(path){const name=path.split('/').pop().toLowerCase();return name.includes('.')?'.'+name.split('.').pop():''}
function modeFor(path){const e=extOf(path);return ({'.js':'javascript','.mjs':'javascript','.cjs':'javascript','.ts':'javascript','.jsx':'javascript','.tsx':'javascript','.html':'htmlmixed','.htm':'htmlmixed','.css':'css','.scss':'css','.sass':'css','.less':'css','.py':'python','.pyw':'python','.sh':'shell','.bash':'shell','.zsh':'shell','.fish':'shell','.md':'markdown','.json':{name:'javascript',json:true},'.xml':'xml','.svg':'xml','.sql':'text/x-sql','.c':'text/x-csrc','.cc':'text/x-c++src','.cpp':'text/x-c++src','.h':'text/x-csrc','.hpp':'text/x-c++src','.java':'text/x-java','.rs':'text/x-rust','.go':'text/x-go','.php':'application/x-httpd-php'}[e]||'text/plain')}
function themeMode(){return style.theme==='light'?'eclipse':style.theme==='dracula'?'dracula':'material-darker'}
function applyStyle(){document.body.dataset.theme=style.theme||'dark';document.documentElement.style.setProperty('--sidebar',(style.sidebarWidth||280)+'px');document.documentElement.style.setProperty('--term',(style.terminalHeight||280)+'px');document.documentElement.style.setProperty('--editor-size',(style.editorFontSize||14)+'px');editor.setOption('theme',themeMode());editor.setOption('lineWrapping',style.wordWrap!==false);term.options.fontSize=style.terminalFontSize||14;try{fitAddon.fit();sendWS({type:'resize',cols:term.cols,rows:term.rows})}catch(e){}}
async function loadStyle(){style=await api('/api/style');envStatus=!!style.envEnabled;applyStyle()}
async function loadRoots(){const d=await api('/api/roots');roots=d.roots;$('roots').innerHTML='';roots.forEach((r,i)=>{const el=document.createElement('div');el.className='root';el.innerHTML=icon(r.kind==='home'?'fa-solid fa-house':'fa-solid fa-hard-drive')+'<span>'+escapeHtml(r.name)+'</span>';el.onclick=()=>selectRoot(r);$('roots').appendChild(el);if(i===0)selectRoot(r)})}
async function selectRoot(root){currentRoot=root;document.querySelectorAll('.root').forEach(x=>x.classList.remove('active'));[...document.querySelectorAll('.root')].find(x=>x.textContent===root.name)?.classList.add('active');openDirs=new Set([root.path]);selectedPath=root.path;selectedType='directory';await renderTree()}
async function renderTree(){if(!currentRoot)return;$('tree').innerHTML='<div class="tree-empty">Loading...</div>';try{$('tree').innerHTML=await buildDir(currentRoot.path,0)||'<div class="tree-empty">Empty directory</div>';bindTree()}catch(e){$('tree').innerHTML='<div class="tree-empty">'+escapeHtml(e.message)+'</div>'}}
async function buildDir(path,depth){let d;try{d=await api('/api/list?path='+encodeURIComponent(path))}catch(e){return `<div class="tree-empty">${escapeHtml(e.message)}</div>`}let html='';for(const item of d.entries){const pad=8+depth*17;const isDir=item.type==='directory';const expanded=openDirs.has(item.path);html+=`<div class="tree-row ${isDir?'dir':''} ${selectedPath===item.path?'selected':''}" data-path="${encodeURIComponent(item.path)}" data-type="${item.type}" data-protected="${item.protected?'1':'0'}" style="padding-left:${pad}px">${isDir?`<span class="arrow">${expanded?'▾':'▸'}</span>`:'<span class="arrow"></span>'}<i class="file-icon ${item.icon}"></i><span class="name">${escapeHtml(item.name)}</span>${!isDir?`<span class="meta">${formatSize(item.size)}</span>`:''}</div>`;if(isDir&&expanded)html+=await buildDir(item.path,depth+1)}return html}
function bindTree(){document.querySelectorAll('.tree-row').forEach(row=>{const path=decodeURIComponent(row.dataset.path);const type=row.dataset.type;row.addEventListener('click',e=>{if(longTriggered){longTriggered=false;return}selectedPath=path;selectedType=type;if(type==='directory'){openDirs.has(path)?openDirs.delete(path):openDirs.add(path);renderTree()}else openFile(path)});row.addEventListener('contextmenu',e=>{e.preventDefault();selectedPath=path;selectedType=type;showContext(e.clientX,e.clientY)});row.addEventListener('touchstart',e=>{longTriggered=false;longTimer=setTimeout(()=>{longTriggered=true;selectedPath=path;selectedType=type;const t=e.touches[0];showContext(t.clientX,t.clientY)},550)},{passive:true});row.addEventListener('touchend',()=>clearTimeout(longTimer));row.addEventListener('touchmove',()=>clearTimeout(longTimer))})}
function fileIconClient(path){const e=path.split('/').pop().toLowerCase();if(e==='.env'||e.startsWith('.env.'))return 'fa-solid fa-gears';const ext=extOf(path).slice(1);return EXTENSIONS_CLIENT[ext]||'fa-solid fa-file'}
const EXTENSIONS_CLIENT={js:'fa-brands fa-js',mjs:'fa-brands fa-js',cjs:'fa-brands fa-js',ts:'fa-brands fa-js',jsx:'fa-brands fa-react',tsx:'fa-brands fa-react',html:'fa-brands fa-html5',htm:'fa-brands fa-html5',css:'fa-brands fa-css3-alt',scss:'fa-brands fa-sass',py:'fa-brands fa-python',md:'fa-brands fa-markdown',json:'fa-solid fa-file-code',svg:'fa-solid fa-bezier-curve',sh:'fa-solid fa-terminal',bash:'fa-solid fa-terminal',zsh:'fa-solid fa-terminal',php:'fa-brands fa-php',java:'fa-brands fa-java',go:'fa-brands fa-golang',rs:'fa-brands fa-rust'};
function pushRecent(path){if(!path||path===PROTECTED_INSTALLER_CLIENT)return;recentFiles=[path,...recentFiles.filter(x=>x!==path)].slice(0,20);renderTabs();saveState()}
function removeRecent(path){recentFiles=recentFiles.filter(x=>x!==path);renderTabs();saveState()}
function renderTabs(){const tabs=$('tabs');tabs.innerHTML='';if(!recentFiles.length){const placeholder=document.createElement('div');placeholder.className='tab';placeholder.innerHTML=icon('fa-solid fa-code')+'<span>No file open</span>';tabs.appendChild(placeholder)}else{recentFiles.forEach(path=>{const tab=document.createElement('div');tab.className='tab '+(path===currentFile?'active':'');tab.innerHTML=icon(fileIconClient(path))+'<span class="tab-name">'+escapeHtml(path.split('/').pop())+'</span><span class="tab-close" title="Close">×</span>';tab.onclick=e=>{if(e.target.closest('.tab-close')){removeRecent(path);if(path===currentFile){const next=recentFiles[0]||null;if(next)openFile(next);else closeFile()}}else openFile(path)};tabs.appendChild(tab)})}const tools=document.createElement('div');tools.className='editor-tools';tools.innerHTML='<button class="small-btn" id="runBtn" title="Execute"><i class="fa-solid fa-play"></i></button><button class="small-btn" id="liveBtn" title="Live Code"><i class="fa-solid fa-bolt"></i></button><button class="small-btn" id="fileConfigBtn" title="File settings"><i class="fa-solid fa-sliders"></i></button>';tabs.appendChild(tools);$('runBtn').onclick=executeCurrent;$('liveBtn').onclick=toggleLive;$('fileConfigBtn').onclick=fileSettings}
async function openFile(path){if(isProtectedInstallerClient(path)){toast('Protected file');return}$('editorLoading').classList.remove('hidden');$('emptyEditor').classList.add('hidden');try{const d=await api('/api/read?path='+encodeURIComponent(path));currentFile=path;currentParent=path.substring(0,path.lastIndexOf('/'))||'/';editor.setOption('mode',modeFor(path));editor.setValue(d.content);editor.clearHistory();recentFiles=[path,...recentFiles.filter(x=>x!==path)].slice(0,20);renderTabs();saveState();if(d.protected&&!envStatus){toast('Environment values are hidden');}else toast('Loaded '+path.split('/').pop());scheduleLint();if(liveEnabled)updateLive()}catch(e){toast(e.message)}finally{$('editorLoading').classList.add('hidden')}}
function closeFile(){currentFile=null;editor.setValue('');$('emptyEditor').classList.remove('hidden');renderTabs();setLive(false);saveState()}
function saveFile(){if(!currentFile)return;if(isEnvFileClient(currentFile)&&!envStatus){toast('Enable .env protection override first');return}api('/api/write',{method:'PUT',body:JSON.stringify({path:currentFile,content:editor.getValue()})}).then(()=>{toast('Saved');renderTree();saveState();scheduleLint()}).catch(e=>toast(e.message))}
editor.on('change',()=>{if(!currentFile)return;clearTimeout(saveTimer);saveTimer=setTimeout(saveFile,650);clearTimeout(lintTimer);lintTimer=setTimeout(scheduleLint,450);if(liveEnabled){clearTimeout(liveTimer);liveTimer=setTimeout(updateLive,180)};renderTabs()});
async function saveState(){try{await api('/api/state',{method:'PUT',body:JSON.stringify({openFiles:recentFiles,lastFile:currentFile})})}catch(e){}}
function showContext(x,y){const menu=$('contextMenu');menu.classList.add('open');const w=menu.offsetWidth,h=menu.offsetHeight;menu.style.left=Math.min(x,innerWidth-w-8)+'px';menu.style.top=Math.min(y,innerHeight-h-8)+'px';menu.querySelectorAll('[data-action]').forEach(b=>b.style.display='flex');if(selectedType==='file')menu.querySelector('[data-action=terminal]').style.display='none';else menu.querySelector('[data-action=open]').style.display='flex'}
function hideContext(){$('contextMenu').classList.remove('open')}
document.addEventListener('click',e=>{if(!e.target.closest('#contextMenu'))hideContext()});
$('contextMenu').addEventListener('click',e=>{const b=e.target.closest('[data-action]');if(!b)return;const a=b.dataset.action;hideContext();if(a==='open'){selectedType==='directory'?(openDirs.add(selectedPath),renderTree()):openFile(selectedPath)}else if(a==='rename')renameSelected();else if(a==='file')createItem('file');else if(a==='folder')createItem('directory');else if(a==='terminal')terminalHere();else if(a==='delete')deleteSelected()});
function parentForNew(){if(selectedType==='directory')return selectedPath;if(selectedPath)return selectedPath.substring(0,selectedPath.lastIndexOf('/'))||HOME;return currentRoot?.path||HOME}
function createItem(type){openModal(type==='file'?'New file':'New folder',`<div class="modal-row"><label>Parent</label><input id="modalParent" value="${escapeHtml(parentForNew())}" disabled></div><div class="modal-row"><label>Name</label><input id="modalName" placeholder="${type==='file'?'script.py':'folder'}" autofocus></div>`,async()=>{const name=$('modalName').value.trim();if(!name)return;const parent=parentForNew();const d=await api('/api/create',{method:'POST',body:JSON.stringify({parent,name,type})});closeModal();selectedPath=d.path;selectedType=type==='directory'?'directory':'file';openDirs.add(parent);await renderTree();toast('Created '+name);if(type==='file')openFile(d.path)});setTimeout(()=>$('modalName')?.focus(),60)}
function renameSelected(){if(!selectedPath||isProtectedInstallerClient(selectedPath))return;const old=selectedPath.split('/').pop();openModal('Rename',`<div class="modal-row"><label>Current name</label><input value="${escapeHtml(old)}" disabled></div><div class="modal-row"><label>New name</label><input id="modalName" value="${escapeHtml(old)}"></div>`,async()=>{const name=$('modalName').value.trim();if(!name)return;const oldPath=selectedPath;const d=await api('/api/rename',{method:'POST',body:JSON.stringify({path:oldPath,name})});if(currentFile===oldPath)currentFile=d.path;recentFiles=recentFiles.map(x=>x===oldPath?d.path:x);selectedPath=d.path;await renderTree();renderTabs();saveState();closeModal();toast('Renamed')});setTimeout(()=>$('modalName')?.focus(),60)}
function deleteSelected(){if(!selectedPath||selectedPath===currentRoot?.path||isProtectedInstallerClient(selectedPath))return;openModal('Delete',`<div style="color:var(--danger);font-size:13px;line-height:1.5">Delete <b>${escapeHtml(selectedPath)}</b>?<br>This action cannot be undone.</div>`,async()=>{await api('/api/delete',{method:'POST',body:JSON.stringify({path:selectedPath})});if(currentFile===selectedPath)closeFile();recentFiles=recentFiles.filter(x=>x!==selectedPath);selectedPath=currentRoot.path;await renderTree();renderTabs();saveState();closeModal();toast('Deleted')},true)}
function fileSettings(){if(!currentFile){toast('No file selected');return}renameSelected()}
function terminalHere(){if(!selectedPath)return;const path=selectedType==='directory'?selectedPath:selectedPath.substring(0,selectedPath.lastIndexOf('/'));sendWS({type:'cwd',path});$('terminalPanel').classList.remove('minimized');fitTerminal();toast('Terminal changed to '+path)}
function openModal(title,body,action,danger=false){modalAction=action;$('modalTitle').textContent=title;$('modalBody').innerHTML=body;$('modalConfirm').textContent=danger?'Delete':'Confirm';$('modalConfirm').className='btn '+(danger?'danger':'primary');$('modalOverlay').classList.add('open')}
function closeModal(){$('modalOverlay').classList.remove('open');modalAction=null}
$('modalConfirm').onclick=async()=>{if(!modalAction)return;try{await modalAction()}catch(e){toast(e.message)}};$('modalCancel').onclick=closeModal;$('modalClose').onclick=closeModal;$('modalOverlay').addEventListener('click',e=>{if(e.target===$('modalOverlay'))closeModal()});
$('newFileBtn').onclick=()=>createItem('file');$('newFolderBtn').onclick=()=>createItem('directory');$('refreshBtn').onclick=renderTree;$('saveBtn').onclick=saveFile;
$('menuBtn').onclick=()=>{$('sidebar').classList.toggle('open');$('backdrop').classList.toggle('show')};$('backdrop').onclick=()=>{$('sidebar').classList.remove('open');$('backdrop').classList.remove('show')};
$('clearTermBtn').onclick=()=>term.clear();
$('minTermBtn').onclick=()=>toggleTerminalMinimize();
$('liveClose').onclick=()=>setLive(false);
function toggleTerminalMinimize(){const panel=$('terminalPanel');const mini=panel.classList.toggle('minimized');$('minTermBtn').innerHTML=icon(mini?'fa-solid fa-chevron-up':'fa-solid fa-chevron-down');setTimeout(fitTerminal,90)}
function terminalResizeStart(e){if(e.pointerType==='mouse'&&e.button!==0)return;e.preventDefault();terminalResizePointer=e.pointerId;const move=ev=>{if(terminalResizePointer!==ev.pointerId)return;const mainRect=$('mainPanel').getBoundingClientRect();const newHeight=Math.max(90,Math.min(Math.floor(mainRect.height*.8),Math.floor(mainRect.bottom-ev.clientY)));style.terminalHeight=newHeight;document.documentElement.style.setProperty('--term',newHeight+'px');$('terminalPanel').classList.remove('minimized');$('minTermBtn').innerHTML=icon('fa-solid fa-chevron-down');fitTerminal()};const up=()=>{terminalResizePointer=null;window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',up)};window.addEventListener('pointermove',move);window.addEventListener('pointerup',up);}
$('terminalResizer').addEventListener('pointerdown',terminalResizeStart);$('terminalResizer').addEventListener('dblclick',()=>{style.terminalHeight=280;document.documentElement.style.setProperty('--term','280px');fitTerminal()});
function openSettings(){openModal('Settings',`<div class="modal-row"><label>Theme</label><select id="setTheme"><option value="dark">Dark</option><option value="dracula">Dracula</option><option value="light">Light</option></select></div><div class="modal-row"><label>Editor font size</label><input id="setEditor" type="number" min="10" max="24" value="${style.editorFontSize||14}"></div><div class="modal-row"><label>Terminal font size</label><input id="setTerm" type="number" min="10" max="24" value="${style.terminalFontSize||14}"></div><div class="modal-row"><label>Terminal height</label><input id="setHeight" type="number" min="90" max="700" value="${style.terminalHeight||280}"></div><div class="modal-row"><label>Sidebar width</label><input id="setSide" type="number" min="220" max="450" value="${style.sidebarWidth||280}"></div><div class="modal-row"><label>Word wrap</label><select id="setWrap"><option value="true">Enabled</option><option value="false">Disabled</option></select></div><div class="modal-row switch-row"><div><div style="font-size:12px;font-weight:600">Show .env values</div><div style="font-size:11px;color:var(--muted);margin-top:4px">Disabled by default</div></div><button id="envToggle" class="toggle ${envStatus?'on':''}" type="button"><span></span></button></div><div class="modal-note">${escapeHtml(ENV_MESSAGE)}</div>`,async()=>{style.theme=$('setTheme').value;style.editorFontSize=+$('setEditor').value;style.terminalFontSize=+$('setTerm').value;style.terminalHeight=+$('setHeight').value;style.sidebarWidth=+$('setSide').value;style.wordWrap=$('setWrap').value==='true';await api('/api/style',{method:'PUT',body:JSON.stringify(style)});applyStyle();closeModal();toast('Settings saved')});$('setTheme').value=style.theme;$('setWrap').value=String(style.wordWrap!==false);$('envToggle').onclick=async()=>{if(envStatus){envStatus=false;await api('/api/env',{method:'PUT',body:JSON.stringify({enabled:false})});$('envToggle').classList.remove('on');if(currentFile&&isEnvFileClient(currentFile))openFile(currentFile);toast('Environment values hidden')}else{await confirmEnvEnable();if(envStatus)$('envToggle').classList.add('on')}}}
$('settingsBtn').onclick=openSettings;

const ENV_MESSAGE='Sorry, but for your protection, this feature is disabled by default. Go to Termux, and in the command tab created when you ran it, there will be a command line ">>>". Type ".env enable".';
const PROTECTED_INSTALLER_CLIENT='vstermu-installer.py';
function isEnvFileClient(path){const n=(path||'').split('/').pop().toLowerCase();return n==='.env'||n.startsWith('.env.')}
function isProtectedInstallerClient(path){return (path||'').split('/').pop()===PROTECTED_INSTALLER_CLIENT}
async function confirmEnvEnable(){return new Promise(resolve=>{openModal('Enable .env values',`<div style="font-size:13px;line-height:1.6">${escapeHtml(ENV_MESSAGE)}<br><br>Enable viewing .env values in VStermu-x?</div>`,async()=>{await api('/api/env',{method:'PUT',body:JSON.stringify({enabled:true})});envStatus=true;style.envEnabled=true;closeModal();if(currentFile&&isEnvFileClient(currentFile))openFile(currentFile);toast('Environment values enabled');resolve(true)},false);})}

let ws=null;
let reconnectTimer=null;
function sendWS(packet){if(ws&&ws.readyState===1)ws.send(JSON.stringify(packet))}
function connectTerminal(){const proto=location.protocol==='https:'?'wss':'ws';ws=new WebSocket(`${proto}://${location.host}/ws/terminal`);ws.onopen=()=>{$('termState').textContent='connected';term.focus();fitTerminal()};ws.onmessage=e=>term.write(e.data);ws.onclose=()=>{$('termState').textContent='reconnecting';clearTimeout(reconnectTimer);reconnectTimer=setTimeout(connectTerminal,1200)};ws.onerror=()=>{}}
function handleCapturedEnvInput(data){for(const ch of data){if(ch==='\u001b'){flushEnvCapture();sendWS({type:'input',data:ch});continue}if(ch==='\r'||ch==='\n'){if(envCaptureMode){const cmd=terminalLineCapture.trim();term.write('\r\n');terminalLineCapture='';envCaptureMode=false;if(cmd==='.env enable'){confirmEnvEnable()}else if(cmd==='.env unenable'){setEnvDisabledFromTerminal()}else if(cmd==='.env status'){term.write(`.env enabled: ${envStatus}\r\n`)}else if(cmd==='.env help'){term.write('.env enable\r\n.env unenable\r\n.env status\r\n.env help\r\n')}else{sendWS({type:'input',data:cmd+'\r'})}}else{sendWS({type:'input',data:ch})}continue}if(ch==='\b'||ch==='\x7f'){if(envCaptureMode){if(terminalLineCapture.length){terminalLineCapture=terminalLineCapture.slice(0,-1);term.write('\b \b')}continue}sendWS({type:'input',data:ch});continue}if(ch.charCodeAt(0)<32){flushEnvCapture();sendWS({type:'input',data:ch});continue}const next=terminalLineCapture+ch;if(!envCaptureMode){if(next==='.') {envCaptureMode=true;terminalLineCapture=next;term.write(ch);continue}sendWS({type:'input',data:ch});continue}if('.env'.startsWith(next)||next.startsWith('.env')){terminalLineCapture=next;term.write(ch)}else{const buffered=terminalLineCapture+ch;flushEnvCapture();sendWS({type:'input',data:buffered})}}}
function flushEnvCapture(){if(!envCaptureMode)return;const buffered=terminalLineCapture;if(buffered){sendWS({type:'input',data:buffered})}terminalLineCapture='';envCaptureMode=false}
async function setEnvDisabledFromTerminal(){await api('/api/env',{method:'PUT',body:JSON.stringify({enabled:false})});envStatus=false;style.envEnabled=false;term.write('.env values disabled in VStermu-x\r\n');if(currentFile&&isEnvFileClient(currentFile))openFile(currentFile)}
term.onData(data=>handleCapturedEnvInput(data));
term.onResize(size=>sendWS({type:'resize',cols:size.cols,rows:size.rows}));
function fitTerminal(){try{fitAddon.fit();sendWS({type:'resize',cols:term.cols,rows:term.rows})}catch(e){}}
window.addEventListener('resize',()=>{clearTimeout(window.fitTimer);window.fitTimer=setTimeout(fitTerminal,60)});

function hintLanguage(){if(!currentFile)return'text';const e=extOf(currentFile);return ({'.py':'python','.pyw':'python','.js':'javascript','.mjs':'javascript','.cjs':'javascript','.jsx':'javascript','.ts':'typescript','.tsx':'typescript','.html':'html','.htm':'html','.css':'css','.scss':'css','.sass':'css','.less':'css','.sh':'shell','.bash':'shell','.zsh':'shell','.fish':'shell','.json':'json','.sql':'sql','.java':'java','.c':'c','.h':'c','.cc':'cpp','.cpp':'cpp','.hpp':'cpp','.rs':'rust','.go':'go','.php':'php'}[e]||'text')}
function packageHintsForLanguage(lang){const base=new Set(LANGUAGE_HINTS_LOCAL[lang]||[]);Object.values(LIBRARY_HINTS_LOCAL).forEach(values=>values.forEach(x=>base.add(x)));return [...base]}
const LANGUAGE_HINTS_LOCAL={python:['False','None','True','and','as','assert','async','await','break','class','continue','def','elif','else','except','finally','for','from','global','if','import','in','is','lambda','not','or','pass','raise','return','try','while','with','yield','print','len','range','enumerate','zip','map','filter','sum','min','max','sorted','isinstance','open','str','int','float','bool','bytes','list','tuple','set','dict','object','super','Exception','ValueError','TypeError','RuntimeError','KeyError','IndexError','Path','os','sys','json','re','time','math','random','datetime','asyncio','logging','subprocess','threading','typing','collections','functools','itertools','requests','flask','FastAPI','pydantic','pytest','discord','commands','tasks','app_commands','Bot','Client','Embed','Intents','Interaction','Message','User','Member','Guild','TextChannel','VoiceChannel','Webhook','File','ui','View','Button','Select','Modal','Cog','Context','aiohttp','uvicorn','numpy','pandas'],javascript:['const','let','var','function','return','if','else','for','while','switch','case','break','continue','try','catch','finally','throw','new','class','extends','import','export','from','default','async','await','this','super','true','false','null','undefined','console','window','document','globalThis','JSON','Math','Date','Promise','Map','Set','Array','Object','String','Number','Boolean','RegExp','Error','URL','fetch','WebSocket','setTimeout','setInterval','clearTimeout','clearInterval','require','module','process','Buffer','fs','path','os','http','https','events','stream','express','discord','Client','GatewayIntentBits','Partials','Collection','EmbedBuilder','ActionRowBuilder','ButtonBuilder','ButtonStyle','StringSelectMenuBuilder','ModalBuilder','TextInputBuilder','REST','Routes','SlashCommandBuilder','PermissionsBitField','axios','react','useState','useEffect','useMemo','useRef'],typescript:[],css:['align-items','justify-content','display','position','margin','padding','width','height','color','background','background-color','border','border-radius','box-shadow','font-family','font-size','font-weight','line-height','gap','grid','grid-template-columns','grid-template-rows','flex-direction','flex-wrap','overflow','opacity','transform','transition','animation','z-index'],html:['html','head','body','title','meta','link','style','script','main','header','footer','nav','section','article','aside','div','span','p','a','button','input','textarea','select','option','label','form','table','thead','tbody','tr','th','td','ul','ol','li','img','video','audio','canvas','svg','path','iframe','details','summary','class','id','src','href','style','title','alt','width','height','type','name','value','placeholder','disabled','checked','selected','aria-label','role','data-'],shell:['cd','pwd','ls','cp','mv','rm','mkdir','touch','cat','less','grep','find','sed','awk','echo','printf','export','unset','source','alias','which','type','chmod','ps','kill','env','ssh','curl','wget','git','python','node','npm','npx','pip','termux-open'],json:['true','false','null'],sql:['SELECT','FROM','WHERE','INSERT','UPDATE','DELETE','CREATE','ALTER','DROP','JOIN','LEFT JOIN','RIGHT JOIN','INNER JOIN','GROUP BY','ORDER BY','HAVING','LIMIT','OFFSET','AS','AND','OR','NOT','NULL','VALUES'],java:['public','private','protected','class','interface','extends','implements','static','final','void','int','long','double','float','boolean','char','new','this','super','return','if','else','for','while','switch','try','catch','finally','package','import','throws','throw','String','System','List','Map','Set','Optional'],c:['include','define','ifdef','ifndef','endif','struct','enum','typedef','const','static','extern','inline','void','int','char','short','long','float','double','size_t','uint8_t','uint16_t','uint32_t','uint64_t','NULL','printf','scanf','malloc','calloc','realloc','free','memcpy','memset','strlen'],cpp:['include','namespace','using','class','struct','public','private','protected','virtual','override','final','template','typename','constexpr','auto','decltype','nullptr','std','vector','string','unordered_map','map','set','optional','variant','unique_ptr','shared_ptr','make_unique','make_shared','cout','cin','endl'],rust:['fn','let','mut','pub','impl','trait','struct','enum','match','if','else','loop','while','for','in','use','mod','crate','self','Self','async','await','move','const','static','type','where','Result','Option','Some','None','Vec','String','HashMap','println!','format!'],go:['package','import','func','var','const','type','struct','interface','map','chan','go','defer','select','switch','case','default','if','else','for','range','return','error','string','int','bool','byte','rune','fmt','context','http','json'],php:['<?php','echo','function','class','interface','trait','extends','implements','namespace','use','public','protected','private','static','final','abstract','return','if','else','foreach','while','match','array','string','int','float','bool','null','true','false','isset','empty','json_encode','json_decode']};
LANGUAGE_HINTS_LOCAL.typescript=LANGUAGE_HINTS_LOCAL.javascript.concat(['interface','type','enum','namespace','readonly','public','private','protected','implements','declare','never','unknown','any','void','keyof','Partial','Pick','Omit','Record','PromiseLike']);
const LIBRARY_HINTS_LOCAL={'discord.py':['discord','discord.ext','commands','app_commands','tasks','Client','Bot','AutoShardedBot','Intents','Embed','Interaction','Message','User','Member','Guild','Role','TextChannel','VoiceChannel','Thread','Webhook','File','Attachment','Permissions','PermissionOverwrite','Colour','Color','HTTPException','Forbidden','NotFound','ui','View','Button','Select','Modal','TextInput','Cog','Context','check','cooldown','command','hybrid_command','tree','setup_hook','on_ready','on_message','on_interaction','send','reply','edit','delete','fetch','create','add_roles','remove_roles','kick','ban','timeout','purge','history','wait_for','change_presence','load_extension','reload_extension'],'discord.js':['discord.js','Client','GatewayIntentBits','Partials','Collection','Events','ActivityType','EmbedBuilder','AttachmentBuilder','ActionRowBuilder','ButtonBuilder','ButtonStyle','StringSelectMenuBuilder','StringSelectMenuOptionBuilder','RoleSelectMenuBuilder','ChannelSelectMenuBuilder','UserSelectMenuBuilder','MentionableSelectMenuBuilder','ModalBuilder','TextInputBuilder','TextInputStyle','ChatInputCommandInteraction','ButtonInteraction','ModalSubmitInteraction','REST','Routes','SlashCommandBuilder','PermissionFlagsBits','PermissionsBitField','MessageFlags','ChannelType','ComponentType','Attachment','Message','User','Guild','GuildMember','TextChannel','VoiceChannel','WebhookClient'],'flask':['Flask','request','jsonify','Response','redirect','url_for','render_template','abort','session','g','Blueprint','send_file','send_from_directory','make_response','flash','current_app','route','get','post','put','delete','before_request','after_request','errorhandler'],'fastapi':['FastAPI','APIRouter','Request','Response','HTTPException','Depends','Query','Path','Body','Header','Cookie','Form','File','UploadFile','WebSocket','BackgroundTasks','status','Security','OAuth2PasswordBearer'],'express':['express','Router','Request','Response','NextFunction','json','urlencoded','static','listen','use','get','post','put','patch','delete','send','status','redirect','render','download','cookie'],'react':['React','ReactDOM','useState','useEffect','useMemo','useCallback','useRef','useReducer','useContext','useLayoutEffect','useId','useTransition','useDeferredValue','memo','forwardRef','lazy','Suspense','Fragment','createElement','createRoot','StrictMode'],'node':['process','Buffer','console','require','module','__dirname','__filename','global','setImmediate','clearImmediate','setTimeout','setInterval','clearTimeout','clearInterval','fetch','AbortController','URL','URLSearchParams','TextEncoder','TextDecoder','EventEmitter','Readable','Writable','Transform','Duplex','fs','path','os','crypto','http','https','url','events','stream','util','child_process','worker_threads','readline','zlib']};
function customHint(cm){const lang=hintLanguage();const list=packageHintsForLanguage(lang);const cursor=cm.getCursor();const token=cm.getTokenAt(cursor);const word=(token.string||'').match(/[\w$.-]*$/)?.[0]||'';const lower=word.toLowerCase();const filtered=list.filter(x=>x.toLowerCase().startsWith(lower)).slice(0,200);const line=cm.getLine(cursor.line);if(lang==='html'&&/<[\w-]*$/.test(line)){return CodeMirror.hint.html(cm)}if(lang==='javascript'||lang==='typescript'){const base=CodeMirror.hint.javascript(cm);if(base&&base.list){const all=[...new Set(base.list.concat(filtered))];return {list:all,from:base.from,to:base.to}}}if(lang==='css'){const base=CodeMirror.hint.css(cm);if(base&&base.list)return {list:[...new Set(base.list.concat(filtered))],from:base.from,to:base.to}}if(lang==='html'){const base=CodeMirror.hint.html(cm);if(base&&base.list)return {list:[...new Set(base.list.concat(filtered))],from:base.from,to:base.to}}if(lang==='xml'){const base=CodeMirror.hint.xml(cm);if(base&&base.list)return base}if(!filtered.length&&word)return CodeMirror.hint.anyword(cm);const from=CodeMirror.Pos(cursor.line,cursor.ch-word.length);return {list:filtered.length?filtered:CodeMirror.hint.anyword(cm)?.list||[],from,to:CodeMirror.Pos(cursor.line,cursor.ch)}}
function showAutocomplete(cm){const result=customHint(cm);if(result)cm.showHint({hint:()=>result,completeSingle:false})}
editor.on('inputRead',(cm,change)=>{if(change.text.join('').match(/[\w$.-]$/))showAutocomplete(cm)});

async function scheduleLint(){if(!currentFile)return;clearLintMarks();try{const d=await api('/api/lint',{method:'POST',body:JSON.stringify({path:currentFile,content:editor.getValue()})});const anns=d.annotations||[];for(const ann of anns){const line=Math.max(0,Math.min(editor.lineCount()-1,ann.line||0));const text=editor.getLine(line)||'';const start=Math.max(0,Math.min(text.length,ann.start||0));const end=Math.max(start+1,Math.min(text.length,ann.end||start+1));lintMarks.push(editor.markText({line,ch:start},{line,ch:end},{className:'cm-manual-error',title:ann.message||'Code error'}))}}catch(e){}}
function clearLintMarks(){lintMarks.forEach(m=>{try{m.clear()}catch(e){}});lintMarks=[]}

function setLive(enabled){liveEnabled=enabled;const panel=$('livePanel');panel.classList.toggle('open',enabled);$('liveBtn')?.classList.toggle('active',enabled);if(!enabled){$('liveFrame').classList.add('hidden');$('liveOutput').classList.add('hidden');$('livePlaceholder').classList.remove('hidden');$('livePlaceholder').textContent='Enable Live Code to preview the current file.';return}updateLive()}
function toggleLive(){setLive(!liveEnabled)}
function liveHtmlDocument(content){return content}
function liveCssDocument(content){return '<!doctype html><html><head><meta charset="utf-8"><style>'+content+'</style></head><body><div style="font-family:Inter,sans-serif;padding:20px">CSS preview</div></body></html>'}
function liveJsDocument(content){const safe=content.replace(/<\/script>/gi,'<\\/script>');return `<!doctype html><html><body style="margin:0;background:#fff;color:#111;font-family:Arial,sans-serif"><div style="padding:16px;font-size:14px">JavaScript live output</div><pre id="out" style="padding:16px;white-space:pre-wrap"></pre><script>(function(){const out=document.getElementById("out");const write=v=>{out.textContent+=(out.textContent?'\n':'')+String(v);};const oldLog=console.log;console.log=(...a)=>{write(a.map(v=>typeof v==="object"?JSON.stringify(v):v).join(" "));oldLog(...a)};try{${safe}}catch(e){write(e.stack||e.message||String(e));}})();<\/script></body></html>`}
function liveMarkdownDocument(content){const html=escapeHtml(content).replace(/^###### (.*)$/gm,'<h6>$1</h6>').replace(/^##### (.*)$/gm,'<h5>$1</h5>').replace(/^#### (.*)$/gm,'<h4>$1</h4>').replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>').replace(/^# (.*)$/gm,'<h1>$1</h1>').replace(/^[-*] (.*)$/gm,'<li>$1</li>').replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/\*([^*]+)\*/g,'<em>$1</em>').replace(/\n\n+/g,'</p><p>').replace(/\n/g,'<br>');return '<!doctype html><html><body style="font-family:Inter,sans-serif;padding:24px;line-height:1.6"><p>'+html+'</p></body></html>'}
async function updateLive(){if(!liveEnabled||!currentFile){return}$('liveLanguage').textContent='';const ext=extOf(currentFile);const lang=(LANGUAGE_LABELS[ext]||ext.slice(1)||'text').toUpperCase();$('liveLanguage').textContent=lang;$('livePlaceholder').classList.add('hidden');const frame=$('liveFrame');const output=$('liveOutput');if(['.html','.htm'].includes(ext)){frame.classList.remove('hidden');output.classList.add('hidden');frame.srcdoc=liveHtmlDocument(editor.getValue());return}if(['.css','.scss','.sass','.less'].includes(ext)){frame.classList.remove('hidden');output.classList.add('hidden');frame.srcdoc=liveCssDocument(editor.getValue());return}if(['.md'].includes(ext)){frame.classList.remove('hidden');output.classList.add('hidden');frame.srcdoc=liveMarkdownDocument(editor.getValue());return}if(['.js','.mjs','.cjs'].includes(ext)){frame.classList.remove('hidden');output.classList.add('hidden');frame.srcdoc=liveJsDocument(editor.getValue());return}frame.classList.add('hidden');output.classList.remove('hidden');output.textContent='Running live preview...';try{const d=await api('/api/live',{method:'POST',body:JSON.stringify({path:currentFile,content:editor.getValue()})});let value='';if(d.output)value+=d.output;if(d.error)value+=(value?'\n':'')+d.error;if(!value)value='No live output.';output.textContent=value}catch(e){output.textContent=e.message}}
const LANGUAGE_LABELS={'.py':'Python','.pyw':'Python','.js':'JavaScript','.mjs':'JavaScript','.cjs':'JavaScript','.ts':'TypeScript','.tsx':'TypeScript','.jsx':'JavaScript','.html':'HTML','.htm':'HTML','.css':'CSS','.scss':'SCSS','.sass':'Sass','.less':'Less','.md':'Markdown','.json':'JSON','.sh':'Shell','.bash':'Bash','.zsh':'Zsh','.fish':'Fish','.php':'PHP','.java':'Java','.c':'C','.cc':'C++','.cpp':'C++','.rs':'Rust','.go':'Go'};

async function executeCurrent(){if(!currentFile){toast('No file selected');return}try{saveFile();const d=await api('/api/execute',{method:'POST',body:JSON.stringify({path:currentFile})});$('terminalPanel').classList.remove('minimized');setTimeout(fitTerminal,60);const cwd=d.cwd||currentParent||HOME;sendWS({type:'cwd',path:cwd});setTimeout(()=>sendWS({type:'input',data:d.command+'\n'}),80);toast(d.command)}catch(e){toast(e.message)}}

function initRecent(state){recentFiles=(state.openFiles||[]).filter(p=>!isProtectedInstallerClient(p)).slice(-20);renderTabs()}
async function init(){try{await loadStyle();await loadRoots();const state=await api('/api/state');initRecent(state);if(state.lastFile)await openFile(state.lastFile)}catch(e){toast(e.message)}connectTerminal();setTimeout(fitTerminal,200)}
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
