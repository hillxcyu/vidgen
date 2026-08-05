import os
import tempfile
import pytest
from src.tools.gcs_storage import save_run, get_saved_runs, delete_saved_run

@pytest.fixture
def temp_output_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield tmp_dir

def test_save_run_local(temp_output_dir):
    entry = save_run(
        run_id="test_run_001",
        original_intent="A panda skiing in Hakuba",
        num_shots=3,
        mode="i2v_chaining",
        output_dir=temp_output_dir
    )

    assert entry["run_id"] == "test_run_001"
    assert entry["original_intent"] == "A panda skiing in Hakuba"

    runs = get_saved_runs(temp_output_dir)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "test_run_001"

def test_delete_saved_run(temp_output_dir):
    save_run(
        run_id="test_run_002",
        original_intent="A red panda dancing",
        num_shots=2,
        mode="reference",
        output_dir=temp_output_dir
    )

    runs_before = get_saved_runs(temp_output_dir)
    assert len(runs_before) == 1

    deleted = delete_saved_run("test_run_002", output_dir=temp_output_dir)
    assert deleted is True

    runs_after = get_saved_runs(temp_output_dir)
    assert len(runs_after) == 0
