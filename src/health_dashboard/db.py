from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from health_dashboard.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


def _is_file_sqlite_url(database_url: str) -> bool:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return False
    return bool(url.database and url.database != ":memory:")


def _configure_sqlite_engine(sqlalchemy_engine: Engine, database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        return

    file_backed = _is_file_sqlite_url(database_url)

    @event.listens_for(sqlalchemy_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        if file_backed:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


settings = get_settings()
engine = create_engine(settings.database_url, future=True, **_engine_kwargs(settings.database_url))
_configure_sqlite_engine(engine, settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    from health_dashboard import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
