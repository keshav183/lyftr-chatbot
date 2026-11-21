import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(
    MOCK_LLM="true",
    LLM_API_KEYS="test-key-1,test-key-2",
    DATABASE_URL=f"sqlite:///{_tmp}/test.db",
    ENABLE_FAILURE_SIMULATION="true",
    CACHE_TYPE="local",
)

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
