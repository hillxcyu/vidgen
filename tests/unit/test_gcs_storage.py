import os
import tempfile
import json
from app.tools.gcs_storage import save_run, get_saved_runs, delete_saved_run, persist_session_state, retrieve_session_state


def test_save_and_retrieve_runs():
    with tempfile.TemporaryDirectory() as tmpdir:
        run_entry = save_run(
            run_id="test_run_123",
            original_intent="A red panda test run",
            num_shots=3,
            mode="i2v_chaining",
            output_dir=tmpdir
        )
        assert run_entry["run_id"] == "test_run_123"
        assert run_entry["original_intent"] == "A red panda test run"

        runs = get_saved_runs(output_dir=tmpdir)
        assert len(runs) >= 1
        assert runs[0]["run_id"] == "test_run_123"

        deleted = delete_saved_run("test_run_123", output_dir=tmpdir)
        assert deleted is True
        runs_after = get_saved_runs(output_dir=tmpdir)
        assert not any(r["run_id"] == "test_run_123" for r in runs_after)


def test_session_state_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_data = {
            "original_intent": "Test intent",
            "status": "completed",
            "num_shots": 3
        }
        persist_session_state("sess_abc", state_data, output_dir=tmpdir)
        restored = retrieve_session_state("sess_abc", output_dir=tmpdir)
        assert restored is not None
        assert restored["original_intent"] == "Test intent"
        assert restored["status"] == "completed"
