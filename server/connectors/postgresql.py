"""
PostgreSQL connector.

Установка:
    pip install psycopg2-binary

Настройки подключения берутся из переменных окружения (см. .env.example):
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""
import os
import psycopg2
import psycopg2.extras

NAME = "PostgreSQL"

STREAM_BATCH_SIZE = int(os.getenv("DB_STREAM_BATCH_SIZE", "2000"))


def _connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def stream_query(query, params=None):
    """
    Потоковое выполнение — то, что реально использует воркер при выгрузке.
    Возвращает (columns, rows_iterator). Соединение и server-side курсор
    закрываются автоматически, когда rows_iterator исчерпан или закрыт.

    Не грузит весь результат в память: cursor.itersize управляет тем,
    сколько строк тянется с сервера БД за один раз.
    """
    conn = _connect()
    # именованный курсор = server-side cursor в psycopg2 (не client-side fetchall)
    cur = conn.cursor(name="simple_report_stream")
    cur.itersize = STREAM_BATCH_SIZE
    cur.execute(query, params or {})

    # У именованных курсоров psycopg2 .description пуст сразу после execute()
    # (execute() там на деле делает DECLARE CURSOR) — появляется только после
    # первого fetch, поэтому забираем первую пачку заранее.
    first_batch = cur.fetchmany(STREAM_BATCH_SIZE)
    columns = [d.name for d in cur.description]

    def _rows():
        try:
            batch = first_batch
            while batch:
                for row in batch:
                    yield row
                batch = cur.fetchmany(STREAM_BATCH_SIZE)
        finally:
            cur.close()
            conn.close()

    return columns, _rows()


def execute_query(query, params=None):
    """Небольшой bounded-запрос целиком в память — для превью (шаг 2), не для выгрузки."""
    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(query, params or {})
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        conn.close()


def get_columns(query):
    """Список имён колонок запроса, без чтения данных — для конструктора отчёта.
    Обычный (не именованный) курсор: .description доступен сразу после execute(),
    в отличие от серверного курсора в stream_query. Выполняется как есть — можно
    передать и вызов хранимой процедуры, не только SELECT."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(query)
        return [d.name for d in cur.description] if cur.description else []
    finally:
        conn.close()


def test_connection(host, port, dbname, user, password):
    conn = psycopg2.connect(host=host, port=int(port), dbname=dbname, user=user, password=password)
    conn.close()
