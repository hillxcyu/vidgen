import os
import tempfile
from unittest.mock import patch
import pytest
from src.tools.gcs_storage import save_run, get_saved_runs, delete_saved_run

@pytest.fixture
def temp_output_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield tmp_dir

@patch("src.tools.gcs_storage.ensure_gcs_bucket", return_value=None)
def test_save_run_local(mock_bucket, temp_output_dir):
    entry = save_run(
        run_id="test_run_001",
        original_intent="A panda skiing in Hakuba",
        num_shots=3,
        mode="i2v_chaining",
        output_dir=temp_output_dir
    )

    assert entry["run_id"] == "test_run_001"
    assert entry["original_intent"] == "A panda skiing in Hakuba"

    with patch("google.cloud.storage.Client", side_effect=Exception("GCS Mock Disabled")):
        runs = get_saved_runs(temp_output_dir)
        assert any(r["run_id"] == "test_run_001" for r in runs)

@patch("src.tools.gcs_storage.ensure_gcs_bucket", return_value=None)
def test_delete_saved_run(mock_bucket, temp_output_dir):
    save_run(
        run_id="test_run_002",
        original_intent="A red panda dancing",
        num_shots=2,
        mode="reference",
        output_dir=temp_output_dir
    )

    with patch("google.cloud.storage.Client", side_effect=Exception("GCS Mock Disabled")):
        runs_before = get_saved_runs(temp_output_dir)
        assert any(r["run_id"] == "test_run_002" for r in runs_before)

        deleted = delete_saved_run("test_run_002", output_dir=temp_output_dir)
        assert deleted is True

        runs_after = get_saved_runs(temp_output_dir)
        assert not any(r["run_id"] == "test_run_002" for r in runs_after)
