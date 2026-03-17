"""Shared test fixtures for NeuralClaw test suite."""
import os
import tempfile
import shutil

import pytest


@pytest.fixture
def tmp_dir():
    """Temporary directory cleaned up after test."""
    d = tempfile.mkdtemp(prefix="neuralclaw_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def db_path(tmp_dir):
    """Temporary database path."""
    return os.path.join(tmp_dir, "test.db")
