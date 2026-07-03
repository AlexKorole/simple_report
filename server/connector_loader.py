"""
Загрузка коннекторов из папки connectors/.

Коннектор — обычный .py файл с:
  NAME = "человекочитаемое имя"
  def stream_query(query, params) -> (columns: list[str], rows: iterator[tuple])
      Потоковое выполнение запроса. НЕ должен грузить весь результат в память —
      это единственное, что реально использует воркер при выгрузке.
  def execute_query(query, params=None) -> list[dict]   (опционально, для будущего превью)
  def test_connection(**kwargs)                          (опционально)

Используется только worker.py — сервер сам с БД не работает.
"""
import importlib.util
import os

CONNECTORS_DIR = os.path.join(os.path.dirname(__file__), "connectors")


def load_connector(name):
    """name — имя файла без .py, например 'postgresql' для connectors/postgresql.py"""
    path = os.path.join(CONNECTORS_DIR, f"{name}.py")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Коннектор '{name}' не найден: {path}")

    spec = importlib.util.spec_from_file_location(f"connectors.{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "stream_query"):
        raise AttributeError(f"Коннектор '{name}' не реализует stream_query(query, params)")

    return module


def list_connectors():
    """Для UI дизайнера отчётов (шаг 2) — какие коннекторы вообще доступны."""
    result = []
    if not os.path.isdir(CONNECTORS_DIR):
        return result
    for fname in sorted(os.listdir(CONNECTORS_DIR)):
        if fname.endswith(".py") and not fname.startswith("_"):
            name = fname[:-3]
            try:
                mod = load_connector(name)
                result.append({"id": name, "name": getattr(mod, "NAME", name)})
            except Exception:
                continue
    return result
