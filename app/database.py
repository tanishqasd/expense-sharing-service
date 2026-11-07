from collections.abc import Iterator
from pathlib import Path
from sqlite3 import Connection

from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import Session

from app.models import Base


DATABASE_PATH = Path(__file__).resolve().parent.parent / "expense_sharing.db"

engine = create_engine(
    URL.create("sqlite+pysqlite", database=str(DATABASE_PATH)),
    connect_args={"autocommit": False},
)


@event.listens_for(engine, "connect")
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


def initialize_database() -> None:
    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session