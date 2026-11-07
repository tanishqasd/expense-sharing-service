from collections.abc import Iterator
from pathlib import Path
from sqlite3 import Connection

from sqlalchemy import Engine, URL, create_engine, event
from sqlalchemy.orm import Session

from app.models import Base


DATABASE_PATH = Path(__file__).resolve().parent.parent / "expense_sharing.db"


def configure_sqlite_connection(
    dbapi_connection: Connection,
    _connection_record: object,
) -> None:
    previous_autocommit = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    try:
        dbapi_connection.execute("PRAGMA foreign_keys = ON").close()
    finally:
        dbapi_connection.autocommit = previous_autocommit

    dbapi_connection.create_function(
        "unicode_casefold",
        1,
        str.casefold,
        deterministic=True,
    )


def create_sqlite_engine(database_path: Path) -> Engine:
    sqlite_engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(database_path)),
        connect_args={"autocommit": False},
    )
    event.listen(sqlite_engine, "connect", configure_sqlite_connection)
    return sqlite_engine


engine = create_sqlite_engine(DATABASE_PATH)


def initialize_database() -> None:
    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session