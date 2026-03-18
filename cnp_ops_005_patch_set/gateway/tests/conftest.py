from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.db import apply_sql_file, init_db
from app.main import create_app


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_gateway.db")


@pytest.fixture()
def app(db_path: str):
    return create_app(db_path=db_path, enable_bridge=False)


@pytest.fixture()
def initialized_db(db_path: str) -> str:
    asyncio.run(init_db(db_path))
    asyncio.run(apply_sql_file(db_path, str(PROJECT_ROOT / "migrations" / "001_ops_tables.sql")))
    return db_path
