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
строки долго до первой строки).

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


# Excel (и другие таблицы) может воспринять ячейку, начинающуюся с =, +, -, @,
# таб или \r, как формулу вместо текста — как случайно (данные из БД никто
# не проверял на этот случай), так и умышленно. Актуальная рекомендация
# OWASP — ставить перед такой строкой одинарную кавычку. Проверяем только
# str (числа/даты приходят из psycopg2 уже типизированными, не str — так что
# легитимные отрицательные числа вроде revenue=-150.00 это не затронет).
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe_cell(value):
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGER_CHARS):
        return "'" + value
    return value


def coerce_params(raw_params, param_defs):
    """Приводит присланные строки к нужным Python-типам согласно конфигу отчёта."""
    types_by_name = {p["name"]: p.get("type", "string") for p in param_defs}
    result = {}
    for name, value in raw_params.items():
        ptype = types_by_name.get(name, "string")
        if ptype == "multilist":
            # value уже список (из JSON) — пустой список = "Все" (без фильтра)
            result[name] = list(value) if value else None
        elif value in (None, ""):
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
    params_path = os.path.join(output_dir, f"{ts}.params.json")

    with open(params_path, "w", encoding="utf-8") as f:
        json.dump(raw_params, f, ensure_ascii=False)

    rows_written = 0
    try:
        with open(part_path, "w", newline="", encoding="utf-8-sig") as f:
            delimiter = os.environ.get("CSV_DELIMITER", ";")
            writer = csv.writer(f, delimiter=delimiter)
            columns, rows = connector.stream_query(config["sql"], params)
            mapping = config.get("column_mapping") or {}
            writer.writerow([mapping.get(c, c) for c in columns])
            for row in rows:
                writer.writerow([_csv_safe_cell(v) for v in row])
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
