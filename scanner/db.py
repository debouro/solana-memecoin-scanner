from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from .config import Settings


class Base(DeclarativeBase):
    pass


COLUMN_ADDITIONS = {
    "tokens": {"logo_url": "VARCHAR(512)"},
    "observations": {
        "price_change_m5": "FLOAT",
        "price_change_h1": "FLOAT",
        "price_change_h24": "FLOAT",
    },
    "extremes": {"confirmed_at": "TIMESTAMP"},
}


def migrate(engine: Engine):
    inspector = inspect(engine)
    for table, columns in COLUMN_ADDITIONS.items():
        if not inspector.has_table(table):
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for column, col_type in columns.items():
            if column not in existing:
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}'))


def make_engine(settings: Settings) -> Engine:
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(settings.database_url, connect_args=connect_args, future=True)


def make_session_factory(settings: Settings):
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    migrate(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    return factory, engine
