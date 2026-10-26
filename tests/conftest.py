from __future__ import annotations

from datetime import date

import pytest

from settings import get_settings
from store.catalog import Catalog, load_catalog
from store.db import make_session_factory
from tools.handlers import ToolContext

TODAY = date(2026, 10, 15)


@pytest.fixture
def catalog() -> Catalog:
    return load_catalog(get_settings().data_dir)


@pytest.fixture
def session():
    s = make_session_factory("sqlite://")()
    yield s
    s.close()


@pytest.fixture
def ctx(session, catalog) -> ToolContext:
    return ToolContext(session=session, catalog=catalog, today=TODAY,
                       conversation_id="conv-test", message_id="msg-test")
