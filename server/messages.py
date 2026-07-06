"""
Словарь сообщений сервера на двух языках.
Язык берётся из .env (LANGUAGE=ru/en).
"""
import os

MESSAGES = {
    "ru": {
        "report_not_found": "отчёт не найден",
        "invalid_filename": "некорректное имя файла",
        "file_not_found": "файл не найден",
        "file_busy": "файл занят, попробуйте позже ({detail})",
        "unknown_error": "неизвестная ошибка",
        "not_found": "не найдено",
        "need_connector_and_query": "нужны connector и query",
        "columns_timeout": "запрос колонок выполняется слишком долго",
        "columns_failed": "не удалось получить колонки",
        "bad_columns_response": "некорректный ответ от report_columns.py",
        "invalid_id_format": "идентификатор может содержать только буквы, цифры, _ и -",
        "id_already_exists": "отчёт с таким идентификатором уже существует",
        "options_timeout": "список значений грузится слишком долго",
        "options_failed": "не удалось получить список значений",
        "bad_options_response": "некорректный ответ от param_options.py",
        "param_not_found": "Параметр '{param}' не найден в конфиге",
        "no_list_or_minmax_query": "У параметра '{param}' не задан list_query/min_query/max_query",
        "connector_no_get_columns": "Коннектор '{connector}' не поддерживает get_columns",
    },
    "en": {
        "report_not_found": "report not found",
        "invalid_filename": "invalid file name",
        "file_not_found": "file not found",
        "file_busy": "file is busy, try again later ({detail})",
        "unknown_error": "unknown error",
        "not_found": "not found",
        "need_connector_and_query": "connector and query are required",
        "columns_timeout": "column lookup is taking too long",
        "columns_failed": "failed to get columns",
        "bad_columns_response": "invalid response from report_columns.py",
        "invalid_id_format": "identifier may only contain letters, digits, _ and -",
        "id_already_exists": "a report with this identifier already exists",
        "options_timeout": "loading the list of values is taking too long",
        "options_failed": "failed to get the list of values",
        "bad_options_response": "invalid response from param_options.py",
        "param_not_found": "Parameter '{param}' not found in config",
        "no_list_or_minmax_query": "Parameter '{param}' has no list_query/min_query/max_query",
        "connector_no_get_columns": "Connector '{connector}' does not support get_columns",
    },
}


def _language():
    return os.environ.get("LANGUAGE", "ru")


def msg(key, **kwargs):
    lang = _language()
    table = MESSAGES.get(lang, MESSAGES["ru"])
    template = table.get(key) or MESSAGES["ru"].get(key) or key
    return template.format(**kwargs) if kwargs else template
