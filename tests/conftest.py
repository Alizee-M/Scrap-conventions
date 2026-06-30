import os
from datetime import date

import pytest
from bs4 import BeautifulSoup

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def load_fixture():
    """Returns a callable that parses a saved HTML snapshot from tests/fixtures/."""
    def _load(name: str) -> BeautifulSoup:
        path = os.path.join(FIXTURES_DIR, name)
        with open(path, "r", encoding="utf-8") as f:
            return BeautifulSoup(f.read(), "lxml")
    return _load


@pytest.fixture
def fixed_today():
    """A date far enough in the past that none of the saved fixtures' events
    get filtered out as 'already happened' — fixtures are real, dated HTML
    snapshots, not synthetic data we control the dates of."""
    return date(2020, 1, 1)
