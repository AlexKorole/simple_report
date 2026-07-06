"""
server.py — единственный долгоживущий процесс. HTTP API + оркестратор воркеров.

Сам с БД не работает вообще (коннекторы нужны только worker.py) — поэтому
не может зависнуть/упасть из-за проблем с БД, максимум "не отвечает" словит
конкретный запрос на запуск отчёта.

Состояние запусков нигде отдельно не хранится — при каждом GET .../runs
папка результатов сканируется заново (см. list_runs). Живые процессы,
запущенные именно этим сервером, отслеживаются в памяти (RUNNING).

Запуск:
    python server.py
Слушает на HOST:PORT из .env (по умолчанию 127.0.0.1:8000).
"""
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

from envfile import load_env_file
from connector_loader import list_connectors
from messages import msg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_env_file(os.path.join(BASE_DIR, ".env"))

# CONFIGS_DIR/RESULTS_DIR по умолчанию — рядом с server.py (случай "просто склонировал
# репозиторий"). Но при установке через npm server.py оказывается внутри node_modules —
# ее могут снести или переустановить, а вместе с ней
# все отчёты и истории выгрузок. Поэтому пути настраиваемые:
# относительный путь в .env берётся относительно BASE_DIR, абсолютный — используется как есть.
CONFIGS_DIR = os.path.join(BASE_DIR, os.environ.get("CONFIGS_DIR", "configs"))
RESULTS_DIR = os.path.join(BASE_DIR, os.environ.get("RESULTS_DIR", "results"))
CLIENT_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "client"))
WORKER_PATH = os.path.join(BASE_DIR, "worker.py")
PARAM_OPTIONS_PATH = os.path.join(BASE_DIR, "param_options.py")
REPORT_COLUMNS_PATH = os.path.join(BASE_DIR, "report_columns.py")
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "3"))
PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")
HELPER_TIMEOUT = int(os.environ.get("HELPER_TIMEOUT_SECONDS", "15"))

PART_RE = re.compile(r"^(?P<ts>\d{8}_\d{6})_pid(?P<pid>\d+)\.csv\.part$")
DONE_RE = re.compile(r"^(?P<ts>\d{8}_\d{6})\.csv$")
ERROR_RE = re.compile(r"^(?P<ts>\d{8}_\d{6})\.error\.txt$")


# ---------------------------------------------------------------------------
# Оркестратор: очередь + лимит одновременных воркеров
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_running = {}  # pid -> {"proc": Popen, "report_id": str}
_pending = queue.Queue()  # элементы: (report_id, params)


def _spawn_worker(report_id, params):
    output_dir = os.path.join(RESULTS_DIR, report_id)
    config_path = os.path.join(CONFIGS_DIR, f"{report_id}.json")
    proc = subprocess.Popen(
        [sys.executable, WORKER_PATH,
         "--config", config_path,
         "--output-dir", output_dir,
         "--params", json.dumps(params)],
        cwd=BASE_DIR,
    )
    with _lock:
        _running[proc.pid] = {"proc": proc, "report_id": report_id}


def _try_start_pending():
    with _lock:
        can_start = MAX_WORKERS - len(_running)
    for _ in range(max(can_start, 0)):
        try:
            report_id, params = _pending.get_nowait()
        except queue.Empty:
            return
        _spawn_worker(report_id, params)


def request_run(report_id, params):
    with _lock:
        has_slot = len(_running) < MAX_WORKERS
    if has_slot:
        _spawn_worker(report_id, params)
    else:
        _pending.put((report_id, params))


def _reaper_loop():
    """Фоновый поток: подчищает завершившиеся процессы, освобождает слоты под очередь."""
    while True:
        with _lock:
            finished = [pid for pid, info in _running.items() if info["proc"].poll() is not None]
            for pid in finished:
                del _running[pid]
        if finished:
            _try_start_pending()
        time.sleep(1)


def is_tracked_running(pid):
    with _lock:
        return pid in _running


def is_pid_alive(pid):
    """Кросс-платформенная проверка "жив ли процесс с таким PID", без установки чего-либо.

    На Windows os.kill(pid, 0) — это НЕ безопасный no-op, как на Unix: он реально
    вызывает TerminateProcess(). Поэтому там используется tasklist вместо os.kill."""
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in out.stdout
        except Exception:
            return True  # не смогли проверить — не считаем это поводом закрывать запуск
    try:
        os.kill(pid, 0)  # на Unix это безопасный no-op запрос к ОС, не убивает
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Работа с конфигами и списком запусков (всё — сканированием файловой системы)
# ---------------------------------------------------------------------------

def list_report_configs():
    if not os.path.isdir(CONFIGS_DIR):
        return []
    result = []
    for fname in sorted(os.listdir(CONFIGS_DIR)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(CONFIGS_DIR, fname), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        result.append({"id": cfg["id"], "name": cfg["name"], "description": cfg.get("description", "")})
    return result


def load_report_config(report_id):
    path = os.path.join(CONFIGS_DIR, f"{report_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_run_params(out_dir, ts):
    path = os.path.join(out_dir, f"{ts}.params.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_report_config(report_id, cfg):
    path = os.path.join(CONFIGS_DIR, f"{report_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def report_config_from_body(report_id, body):
    return {
        "id": report_id,
        "name": body.get("name", ""),
        "description": body.get("description", ""),
        "connector": body.get("connector", "postgresql"),
        "sql": body.get("sql", ""),
        "columns_query": body.get("columns_query") or None,
        "column_mapping": body.get("column_mapping") or {},
        "params": body.get("params", []),
    }


def list_runs(report_id):
    out_dir = os.path.join(RESULTS_DIR, report_id)
    if not os.path.isdir(out_dir):
        return []

    runs = []
    for fname in os.listdir(out_dir):
        full = os.path.join(out_dir, fname)

        m = DONE_RE.match(fname)
        if m:
            st = os.stat(full)
            runs.append({
                "file": fname, "status": "done", "ts": m.group("ts"),
                "size_bytes": st.st_size,
                "params": load_run_params(out_dir, m.group("ts")),
            })
            continue

        m = ERROR_RE.match(fname)
        if m:
            with open(full, "r", encoding="utf-8") as f:
                text = f.read()
            runs.append({
                "file": fname, "status": "error", "ts": m.group("ts"),
                "error": text.strip().splitlines()[-1] if text.strip() else msg("unknown_error"),
                "params": load_run_params(out_dir, m.group("ts")),
            })
            continue

        m = PART_RE.match(fname)
        if m:
            pid = int(m.group("pid"))
            if is_tracked_running(pid):
                status = "running"
            elif is_pid_alive(pid):
                status = "running"  # пережил рестарт сервера, но процесс жив
            else:
                status = "interrupted"  # процесс мёртв, файл недописан — сервер, видимо, перезапускали
            st = os.stat(full)
            runs.append({
                "file": fname, "status": status, "ts": m.group("ts"),
                "size_bytes": st.st_size,
                "params": load_run_params(out_dir, m.group("ts")),
            })
            continue

    runs.sort(key=lambda r: r["ts"], reverse=True)
    return runs


def delete_report(report_id):
    """Удаляет конфиг отчёта и всю папку с историей выгрузок целиком (необратимо)."""
    config_path = os.path.join(CONFIGS_DIR, f"{report_id}.json")
    if not os.path.exists(config_path):
        return False
    os.remove(config_path)
    results_path = os.path.join(RESULTS_DIR, report_id)
    if os.path.isdir(results_path):
        shutil.rmtree(results_path, ignore_errors=True)
    return True


def delete_run(report_id, filename):
    # запрет выхода за пределы папки отчёта через имя файла
    if "/" in filename or "\\" in filename or ".." in filename:
        return False, msg("invalid_filename")
    path = os.path.join(RESULTS_DIR, report_id, filename)
    if not os.path.exists(path):
        return False, msg("file_not_found")
    try:
        os.remove(path)
    except OSError as e:
        # На Windows файл, открытый другим процессом (скачивается прямо сейчас,
        # просканирован антивирусом и т.п.), нельзя удалить — на Unix та же
        # операция тихо сработает всегда. Отдаём это как понятную ошибку клиенту.
        return False, msg("file_busy", detail=e.strerror or e)

    # у файла результата (.csv/.error.txt/.csv.part) и sidecar-файла с параметрами
    # общий префикс — <ts> — удаляем и его, иначе он останется сиротой навсегда
    m = re.match(r"^(\d{8}_\d{6})", filename)
    if m:
        params_path = os.path.join(RESULTS_DIR, report_id, f"{m.group(1)}.params.json")
        if os.path.exists(params_path):
            try:
                os.remove(params_path)
            except OSError:
                pass  # не критично — сам результат уже удалён успешно
    return True, None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[server] {self.address_string()} {fmt % args}\n")

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._json(status, {"error": message})

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/reports":
            return self._json(200, list_report_configs())

        if path == "/api/connectors":
            return self._json(200, list_connectors())

        m = re.match(r"^/api/reports/([^/]+)/params/([^/]+)/options$", path)
        if m:
            return self._param_options(m.group(1), m.group(2))

        m = re.match(r"^/api/reports/([^/]+)/runs/([^/]+)/download$", path)
        if m:
            return self._download(m.group(1), m.group(2))

        m = re.match(r"^/api/reports/([^/]+)/runs$", path)
        if m:
            return self._json(200, list_runs(m.group(1)))

        m = re.match(r"^/api/reports/([^/]+)$", path)
        if m:
            cfg = load_report_config(m.group(1))
            if cfg is None:
                return self._error(404, msg("report_not_found"))
            return self._json(200, cfg)

        return self._static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/preview-columns":
            return self._preview_columns()

        if path == "/api/reports":
            return self._create_report()

        m = re.match(r"^/api/reports/([^/]+)/run$", path)
        if m:
            report_id = m.group(1)
            if load_report_config(report_id) is None:
                return self._error(404, msg("report_not_found"))
            body = self._read_json_body()
            request_run(report_id, body.get("params", {}))
            return self._json(200, {"ok": True})

        return self._error(404, msg("not_found"))

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        m = re.match(r"^/api/reports/([^/]+)$", path)
        if m:
            return self._update_report(m.group(1))

        return self._error(404, msg("not_found"))

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        m = re.match(r"^/api/reports/([^/]+)/runs/([^/]+)$", path)
        if m:
            ok, err = delete_run(m.group(1), m.group(2))
            if not ok:
                return self._error(409, err)
            return self._json(200, {"ok": True})

        m = re.match(r"^/api/reports/([^/]+)$", path)
        if m:
            ok = delete_report(m.group(1))
            if not ok:
                return self._error(404, msg("report_not_found"))
            return self._json(200, {"ok": True})

        return self._error(404, msg("not_found"))

    def _preview_columns(self):
        body = self._read_json_body()
        connector_name = (body.get("connector") or "").strip()
        query = body.get("query") or ""
        if not connector_name or not query.strip():
            return self._error(400, msg("need_connector_and_query"))
        try:
            result = subprocess.run(
                [sys.executable, REPORT_COLUMNS_PATH, "--connector", connector_name, "--query", query],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=HELPER_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return self._error(504, msg("columns_timeout"))
        if result.returncode != 0:
            return self._error(500, result.stderr.strip() or msg("columns_failed"))
        try:
            columns = json.loads(result.stdout)
        except json.JSONDecodeError:
            return self._error(500, msg("bad_columns_response"))
        return self._json(200, columns)

    def _create_report(self):
        body = self._read_json_body()
        report_id = (body.get("id") or "").strip()
        if not ID_RE.match(report_id):
            return self._error(400, msg("invalid_id_format"))
        config_path = os.path.join(CONFIGS_DIR, f"{report_id}.json")
        if os.path.exists(config_path):
            return self._error(409, msg("id_already_exists"))
        save_report_config(report_id, report_config_from_body(report_id, body))
        return self._json(200, {"ok": True, "id": report_id})

    def _update_report(self, report_id):
        config_path = os.path.join(CONFIGS_DIR, f"{report_id}.json")
        if not os.path.exists(config_path):
            return self._error(404, msg("report_not_found"))
        body = self._read_json_body()
        save_report_config(report_id, report_config_from_body(report_id, body))
        return self._json(200, {"ok": True})

    def _param_options(self, report_id, param_name):
        config_path = os.path.join(CONFIGS_DIR, f"{report_id}.json")
        if not os.path.exists(config_path):
            return self._error(404, msg("report_not_found"))
        try:
            result = subprocess.run(
                [sys.executable, PARAM_OPTIONS_PATH, "--config", config_path, "--param", param_name],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=HELPER_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return self._error(504, msg("options_timeout"))
        if result.returncode != 0:
            return self._error(500, result.stderr.strip() or msg("options_failed"))
        try:
            options = json.loads(result.stdout)
        except json.JSONDecodeError:
            return self._error(500, msg("bad_options_response"))
        return self._json(200, options)

    def _download(self, report_id, filename):
        if "/" in filename or "\\" in filename or ".." in filename:
            return self._error(400, msg("invalid_filename"))
        path = os.path.join(RESULTS_DIR, report_id, filename)
        if not os.path.exists(path):
            return self._error(404, msg("file_not_found"))
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(os.path.getsize(path)))
        self.end_headers()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)

    def _static(self, path):
        if path == "/":
            path = "/index.html"
        full = os.path.abspath(os.path.join(CLIENT_DIR, path.lstrip("/")))
        if not full.startswith(CLIENT_DIR) or not os.path.isfile(full):
            return self._error(404, msg("not_found"))

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }
        ext = os.path.splitext(full)[1]
        self.send_response(200)
        self.send_header("Content-Type", content_types.get(ext, "application/octet-stream"))
        with open(full, "rb") as f:
            data = f.read()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    threading.Thread(target=_reaper_loop, daemon=True).start()

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[server] слушаю http://{HOST}:{PORT}  (MAX_WORKERS={MAX_WORKERS})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
