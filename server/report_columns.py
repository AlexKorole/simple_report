"""
report_columns.py — короткоживущий процесс: получить список имён колонок
произвольного запроса (или вызова хранимой процедуры) через коннектор,
напечатать JSON-массив в stdout и завершиться.

В отличие от param_options.py/worker.py работает БЕЗ сохранённого конфига —
отчёт может ещё не существовать (используется конструктором при создании).

Использование:
    python report_columns.py --connector postgresql --query "SELECT * FROM sales_data LIMIT 0"
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
    parser.add_argument("--connector", required=True)
    parser.add_argument("--query", required=True)
    args = parser.parse_args()

    load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

    connector = load_connector(args.connector)
    if not hasattr(connector, "get_columns"):
        print(f"Коннектор '{args.connector}' не поддерживает get_columns", file=sys.stderr)
        sys.exit(1)

    columns = connector.get_columns(args.query)
    print(json.dumps(columns, ensure_ascii=False))


if __name__ == "__main__":
    main()
