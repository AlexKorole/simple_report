# simple_report

Параметризованные SQL-отчёты с выгрузкой в CSV в фоне — для отчётов, которые могут строиться часами или даже сутками. Каждый запуск — отдельный процесс: не блокирует сервер и переживает его рестарт.

## Быстрый старт

```
cd server
pip install -r requirements.txt
cp .env.example .env   # впишите свои настройки БД
python server.py
```

Откройте `http://127.0.0.1:8000` — клиент отдаётся тем же процессом, отдельно поднимать ничего не нужно.

## Через npm

```
npm install simple-report
python node_modules/simple-report/server/server.py
```

(Node здесь используется только как способ доставки файлов на диск — сам сервер на Python, `node` для его работы не нужен.)

## Структура

- `server/` — Python, стандартная библиотека (кроме коннектора к БД)
  - `server.py` — HTTP API + оркестратор воркеров, с БД не работает
  - `worker.py` — отдельный процесс на каждый запуск отчёта, пишет CSV
  - `connectors/` — плагины подключения к БД (образец: `postgresql.py`)
  - `configs/` — конфиги отчётов (SQL-запрос, параметры)
  - `results/` — сюда копятся готовые файлы, по одному на запуск
- `client/` — чистый JS, без сборки и фреймворков

## Как добавить отчёт

Положить `.json` в `server/configs/`, например:

```json
{
  "id": "my_report",
  "name": "Название",
  "connector": "postgresql",
  "sql": "SELECT ... WHERE col = %(param)s",
  "params": [{"name": "param", "view_name": "Параметр", "type": "string"}]
}
```

## Свой коннектор к другой БД

Файл в `server/connectors/`, с `NAME` и функцией `stream_query(query, params) -> (columns, rows)` — см. `postgresql.py` как образец.

## Лицензия

Бесплатно для личного, образовательного и некоммерческого использования — см. [LICENSE](./LICENSE).

Для коммерческого использования нужна отдельная лицензия — см. [LICENSE.commercial](./LICENSE.commercial) или напишите на **korolevalexa@gmail.com**.
