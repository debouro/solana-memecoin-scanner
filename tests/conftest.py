import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scanner.config import Settings
from scanner.db import Base


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def settings():
    return Settings(database_url="sqlite:///:memory:")
