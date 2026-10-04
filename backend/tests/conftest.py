import json
from pathlib import Path

import pytest

from sot.config import load_settings
from sot.core.pack import load_pack
from sot.store.db import DB

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path):
    return load_settings(runtime=tmp_path / "runtime")


@pytest.fixture
def pack(settings):
    return load_pack(settings.pack_dir)


@pytest.fixture
def db():
    return DB(":memory:")


@pytest.fixture
def e1_dir():
    return FIXTURES / "example_e1"


@pytest.fixture
def e1_expected(e1_dir):
    return json.loads((e1_dir / "expected.json").read_text())
