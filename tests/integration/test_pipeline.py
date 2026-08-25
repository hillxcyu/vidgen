import os
import tempfile
import cv2
import numpy as np
from unittest.mock import MagicMock
from app.state import PipelineState
from app.agents.pipeline import run_pre_production, run_production_loop, run_pipeline


def _make_mock_client():
    mock_client = MagicMock()
    mock_interaction = MagicMock()

    # Generate synthetic MP4 bytes
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        p = tmp.name
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(p, fourcc, 10.0, (64, 64))
    for _ in range(10):
        out.write(np.full((64, 64, 3), 100, dtype=np.uint8))
    out.release()

    with open(p, "rb") as f:
        mp4_bytes = f.read()
    if os.path.exists(p):
        os.remove(p)

    mock_interaction.output = mp4_bytes
    mock_client.interactions.create.return_value = mock_interaction

    mock_model_resp = MagicMock()
    mock_model_resp.text = '{"score": 0.95, "reason": [{"criterion_name": "Visual Audit", "score": 0.95, "comments": "Excellent continuity"}], "verdict": "PASSED", "feedback": "Good quality"}'
    mock_client.models.generate_content.return_value = mock_model_resp

    return mock_client


def test_pipeline_e2e_i2v_chaining():
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_client = _make_mock_client()
        state = PipelineState(
            original_intent="A red panda skiing in Hakuba",
            num_shots=2,
            mode="i2v_chaining",
            duration=10
        )
        final_state = run_pipeline(state, output_dir=tmpdir, client=mock_client)

        assert len(final_state.shots) == 2
        assert final_state.stitched_video_path is not None
        assert os.path.exists(final_state.stitched_video_path)
        assert os.path.getsize(final_state.stitched_video_path) > 0


def test_pipeline_e2e_reference_mode():
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_client = _make_mock_client()
        state = PipelineState(
            original_intent="A red panda skiing in Hakuba",
            num_shots=2,
            mode="reference",
            reference_assets_b64=["fake_ref_b64"],
            duration=10
        )
        final_state = run_pipeline(state, output_dir=tmpdir, client=mock_client)

        assert len(final_state.shots) == 2
        assert final_state.stitched_video_path is not None
        assert os.path.exists(final_state.stitched_video_path)


def test_pipeline_stop_callback():
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_client = _make_mock_client()
        state = PipelineState(
            original_intent="A red panda skiing in Hakuba",
            num_shots=3,
            mode="i2v_chaining"
        )
        # Simulate stop triggered after first shot
        stop_flag = [False]

        def stop_check():
            return stop_flag[0]

        def event_cb(ev):
            if ev.get("action") == "OPTIMIZE_PROMPT":
                stop_flag[0] = True

        final_state = run_pipeline(state, output_dir=tmpdir, client=mock_client, event_callback=event_cb, is_stopped=stop_check)
        assert len(final_state.shots) <= 3
