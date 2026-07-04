"""
server.py — единственный долгоживущий процесс. HTTP API + оркестратор воркеров.

Сам с БД не работает вообще (коннекторы нужны только worker.py) — поэтому
не может зависнуть/упасть из-за проблем с БД, максимум "не отвечает" словит
конкретный запрос на запуск отчёта.

Состояние запусков нигде отдельно не хранится — при каждом GET .../runs
папка результатов сканируется заново (см. list_runs). Живые процессы,
запущенные именно этим сервером, отслеживаются в памяти (RUNNING) — только
чтобы уважать MAX_WORKERS и уверенно отличать "точно наш, точно жив" от
"файл .part остался с прошлого запуска сервера, неизвестно жив ли".

Запуск:
    python server.py
Слушает на 127.0.0.1:8000 (см. .env — PORT).
"""
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

from envfile import load_env_file

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIGS_DIR = os.path.join(BASE_DIR, "configs")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
CLIENT_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "client"))
WORKER_PATH = os.path.join(BASE_DIR, "worker.py")
PARAM_OPTIONS_PATH = os.path.join(BASE_DIR, "param_options.py")

load_env_file(os.path.join(BASE_DIR, ".env"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "3"))
PORT = int(os.environ.get("PORT", "8000"))

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
                "error": text.strip().splitlines()[-1] if text.strip() else "неизвестная ошибка",
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


def delete_run(report_id, filename):
    # запрет выхода за пределы папки отчёта через имя файла
    if "/" in filename or "\\" in filename or ".." in filename:
        return False, "некорректное имя файла"
    path = os.path.join(RESULTS_DIR, report_id, filename)
    if not os.path.exists(path):
        return False, "файл не найден"
    try:
        os.remove(path)
    except OSError as e:
        # На Windows файл, открытый другим процессом (скачивается прямо сейчас,
        # просканирован антивирусом и т.п.), нельзя удалить — на Unix та же
        # операция тихо сработает всегда. Отдаём это как понятную ошибку клиенту.
        return False, f"файл занят, попробуйте позже ({e.strerror or e})"

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
                return self._error(404, "отчёт не найден")
            return self._json(200, cfg)

        return self._static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        m = re.match(r"^/api/reports/([^/]+)/run$", path)
        if m:
            report_id = m.group(1)
            if load_report_config(report_id) is None:
                return self._error(404, "отчёт не найден")
            body = self._read_json_body()
            request_run(report_id, body.get("params", {}))
            return self._json(200, {"ok": True})

        return self._error(404, "не найдено")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        m = re.match(r"^/api/reports/([^/]+)/runs/([^/]+)$", path)
        if m:
            ok, err = delete_run(m.group(1), m.group(2))
            if not ok:
                return self._error(409, err)
            return self._json(200, {"ok": True})

        return self._error(404, "не найдено")

    def _param_options(self, report_id, param_name):
        config_path = os.path.join(CONFIGS_DIR, f"{report_id}.json")
        if not os.path.exists(config_path):
            return self._error(404, "отчёт не найден")
        try:
            result = subprocess.run(
                [sys.executable, PARAM_OPTIONS_PATH, "--config", config_path, "--param", param_name],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=15,
            )
        except subprocess.TimeoutExpired:
            return self._error(504, "список значений грузится слишком долго")
        if result.returncode != 0:
            return self._error(500, result.stderr.strip() or "не удалось получить список значений")
        try:
            options = json.loads(result.stdout)
        except json.JSONDecodeError:
            return self._error(500, "некорректный ответ от param_options.py")
        return self._json(200, options)

    def _download(self, report_id, filename):
        if "/" in filename or "\\" in filename or ".." in filename:
            return self._error(400, "некорректное имя файла")
        path = os.path.join(RESULTS_DIR, report_id, filename)
        if not os.path.exists(path):
            return self._error(404, "файл не найден")
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
            return self._error(404, "не найдено")

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

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[server] слушаю http://127.0.0.1:{PORT}  (MAX_WORKERS={MAX_WORKERS})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
