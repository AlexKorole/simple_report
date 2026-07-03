"""
worker.py — отдельный процесс на один запуск отчёта.
 
Запускается сервером (server.py) как subprocess, сам сервер в его работу
дальше не вмешивается — просто следит через proc.poll()/proc.wait().
 
Состояние запуска целиком выражается именем файла в output-dir:
  <ts>_pid<PID>.csv.part   — ещё пишется (PID нужен, чтобы после рестарта
                              сервера можно было проверить os.kill(pid, 0) —
                              жив ли ещё этот процесс, раз сервер уже не
                              родитель этому воркеру и proc.wait() на него
                              не повесить)
  <ts>.csv                  — готово, атомарно переименовано из .part
  <ts>.error.txt              — упало, внутри текст ошибки
 
Никакого отдельного статус-файла/БД для прогресса нет намеренно — размер
.part файла ненадёжен как индикатор (тяжёлый запрос может не отдавать
строки долго до первой строки), а большего для v1 не требуется.
 
Использование:
    python worker.py --config configs/sales_data.json --output-dir results/sales_data --params '{"region": "North", "date_from": "", "date_to": ""}'
"""
import argparse
import csv
import datetime
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from connector_loader import load_connector  # noqa: E402
from envfile import load_env_file  # noqa: E402


def coerce_params(raw_params, param_defs):
    """Приводит присланные строки к нужным Python-типам согласно конфигу отчёта."""
    types_by_name = {p["name"]: p.get("type", "string") for p in param_defs}
    result = {}
    for name, value in raw_params.items():
        ptype = types_by_name.get(name, "string")
        if value in (None, ""):
            result[name] = None
        elif ptype == "number":
            result[name] = float(value) if ("." in str(value)) else int(value)
        elif ptype == "date":
            result[name] = datetime.datetime.strptime(str(value), "%Y-%m-%d").date()
        else:
            result[name] = value
    return result


def run(config_path, output_dir, raw_params):
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    connector = load_connector(config["connector"])
    params = coerce_params(raw_params, config.get("params", []))

    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    pid = os.getpid()
    part_path = os.path.join(output_dir, f"{ts}_pid{pid}.csv.part")
    final_path = os.path.join(output_dir, f"{ts}.csv")

    rows_written = 0
    try:
        columns, rows = connector.stream_query(config["sql"], params)
        with open(part_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(columns)
            for row in rows:
                writer.writerow(row)
                rows_written += 1
        os.replace(part_path, final_path)
        print(f"[worker] done: {rows_written} rows -> {final_path}")
    except Exception:
        err_text = traceback.format_exc()
        print(f"[worker] failed after {rows_written} rows:\n{err_text}", file=sys.stderr)
        if os.path.exists(part_path):
            os.remove(part_path)
        error_path = os.path.join(output_dir, f"{ts}.error.txt")
        with open(error_path, "w", encoding="utf-8") as f:
            f.write(err_text)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="путь к configs/<report>.json")
    parser.add_argument("--output-dir", required=True, help="куда писать результат (results/<report>/)")
    parser.add_argument("--params", default="{}", help="JSON-объект со значениями параметров")
    args = parser.parse_args()

    load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    run(args.config, args.output_dir, json.loads(args.params))


if __name__ == "__main__":
    main()
