from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from health_dashboard.db import _configure_sqlite_engine, _engine_kwargs, _is_file_sqlite_url


def test_file_sqlite_url_detection() -> None:
    assert _is_file_sqlite_url("sqlite:///./data/health_dashboard.db")
    assert not _is_file_sqlite_url("sqlite://")
    assert not _is_file_sqlite_url("sqlite:///:memory:")
    assert not _is_file_sqlite_url("postgresql+psycopg://health:health@localhost/health")


def test_file_sqlite_engine_uses_wal_and_busy_timeout(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'health.db'}"
    engine = create_engine(database_url, future=True, **_engine_kwargs(database_url))
    _configure_sqlite_engine(engine, database_url)

    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA synchronous").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000


def test_memory_sqlite_engine_keeps_memory_journal() -> None:
    database_url = "sqlite://"
    engine = create_engine(
        database_url,
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _configure_sqlite_engine(engine, database_url)

    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "memory"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
