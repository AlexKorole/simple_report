"""
param_options.py — короткоживущий процесс (не фоновая задача): получить варианты
значений для параметра типа multilist/list из его list_query, напечатать JSON
в stdout и завершиться. server.py ждёт его синхронно, с таймаутом.

Использование:
    python param_options.py --config configs/sales_data.json --param products
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from connector_loader import load_connector  # noqa: E402
from envfile import load_env_file  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--param", required=True)
    args = parser.parse_args()

    load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    param = next((p for p in config.get("params", []) if p["name"] == args.param), None)
    if param is None:
        print(f"Параметр '{args.param}' не найден в конфиге", file=sys.stderr)
        sys.exit(1)

    connector = load_connector(config["connector"])

    if param.get("min_query") or param.get("max_query"):
        result = {"min": None, "max": None}
        if param.get("min_query"):
            rows = connector.execute_query(param["min_query"])
            if rows:
                values = list(rows[0].values())
                result["min"] = values[0] if values else None
        if param.get("max_query"):
            rows = connector.execute_query(param["max_query"])
            if rows:
                values = list(rows[0].values())
                result["max"] = values[0] if values else None
        print(json.dumps(result, ensure_ascii=False, default=str))
        return

    if not param.get("list_query"):
        print(f"У параметра '{args.param}' не задан list_query/min_query/max_query", file=sys.stderr)
        sys.exit(1)

    rows = connector.execute_query(param["list_query"])

    options = []
    for row in rows:
        values = list(row.values())
        if not values:
            continue
        value = values[0]
        label = values[1] if len(values) > 1 else values[0]
        options.append({"value": value, "label": label})

    # default=str — на случай если в list_query попадут Decimal/date/etc.
    print(json.dumps(options, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
