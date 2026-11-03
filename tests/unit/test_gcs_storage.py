import os
import tempfile
import json
from unittest.mock import MagicMock
from app.tools.gcs_storage import (
    save_run,
    get_saved_runs,
    delete_saved_run,
    persist_session_state,
    retrieve_session_state,
    ensure_gcs_bucket,
    upload_file_to_gcs,
)


def test_ensure_gcs_bucket_fallback_without_bucket_get_permission():
    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.name = "vital-octagon-19612-vidgen-showcase"
    mock_bucket.exists.side_effect = Exception("403 Forbidden: lacks storage.buckets.get")
    mock_client.bucket.return_value = mock_bucket
    mock_client.get_bucket.side_effect = Exception("403 Forbidden: lacks storage.buckets.get")

    bucket = ensure_gcs_bucket(mock_client, "vital-octagon-19612-vidgen-showcase")
    assert bucket is mock_bucket


def test_upload_file_to_gcs_sets_no_cache():
    mock_bucket = MagicMock()
    mock_bucket.name = "vital-octagon-19612-vidgen-showcase"
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob

    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
        tmp.write(b"fake_video_bytes")
        tmp.flush()
        url = upload_file_to_gcs(mock_bucket, tmp.name, "showcase/vidgen_123/shot_1_999.mp4")

    assert url == "https://storage.googleapis.com/vital-octagon-19612-vidgen-showcase/showcase/vidgen_123/shot_1_999.mp4"
    assert mock_blob.cache_control == "no-cache, max-age=0"
    mock_blob.upload_from_filename.assert_called_once()



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
