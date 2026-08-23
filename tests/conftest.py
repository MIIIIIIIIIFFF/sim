"""Register shared pytest fixtures."""

from __future__ import annotations

import pytest

from tests.helpers import two_day_scenario as _two_day_scenario


@pytest.fixture
def two_day_scenario():
    return _two_day_scenario()
