import os
import tempfile
import base64
import subprocess
from unittest.mock import MagicMock, patch
import cv2
import numpy as np
import pytest
from src.state import PipelineState
from src.agents.stitcher_graph import run_pipeline

def create_synthetic_mp4():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        path = tmp.name
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(path, fourcc, 10.0, (64, 64))
    for i in range(10):
        frame = np.full((64, 64, 3), (i + 1) * 20, dtype=np.uint8)
        out.write(frame)
    out.release()
    with open(path, "rb") as f:
        data = f.read()
    os.remove(path)
    return data

async def mock_run_adk_agent(agent, prompt, media_parts=None, session_service=None):
    if agent.name == "ScreenwriterAgent":
        return '''[
            {"scene_number": 1, "description": "Shot 1: Snow landscape", "camera_angle": "wide"},
            {"scene_number": 2, "description": "Shot 2: Red panda skiing", "camera_angle": "medium"},
            {"scene_number": 3, "description": "Shot 3: Red panda jumping", "camera_angle": "close-up"}
        ]'''
    elif agent.name == "PromptOptimizerAgent":
        return "Enhanced cinematic prompt"
    elif agent.name == "HealthCheckerAgent":
        return "APPROVED"
    elif agent.name == "QualityRaterAgent":
        return '{"score": 0.9, "feedback": "Good quality"}'
    return "OK"

@patch("src.agents.stitcher_graph.run_adk_agent", side_effect=mock_run_adk_agent)
def test_full_pipeline_integration_i2v(mock_adk):
    mock_client = MagicMock()

    # Video generation mock
    fake_mp4_data = create_synthetic_mp4()
    mock_interaction = MagicMock()
    mock_interaction.output_video.data = base64.b64encode(fake_mp4_data).decode("utf-8")
    mock_client.interactions.create.return_value = mock_interaction

    state = PipelineState(
        original_intent="A red panda skiing in Hakuba",
        mode="i2v_chaining"
    )

    with tempfile.TemporaryDirectory() as output_dir:
        result_state = run_pipeline(state, output_dir=output_dir, client=mock_client)

        assert result_state.stitched_video_path is not None
        assert os.path.exists(result_state.stitched_video_path)
        assert os.path.getsize(result_state.stitched_video_path) > 0

        # Verify individual shots and frame extractions
        assert len(result_state.shots) == 3
        for shot in result_state.shots:
            assert shot.status == "completed"
            assert os.path.exists(shot.video_path)

        # Shot 1 and Shot 2 should have extracted terminal frames
        assert result_state.shots[0].extracted_last_frame_b64 is not None
        assert result_state.shots[1].extracted_last_frame_b64 is not None

@patch("src.agents.stitcher_graph.run_adk_agent", side_effect=mock_run_adk_agent)
def test_full_pipeline_integration_reference_mode(mock_adk):
    mock_client = MagicMock()
    fake_mp4_data = create_synthetic_mp4()
    mock_interaction = MagicMock()
    mock_interaction.output_video.data = base64.b64encode(fake_mp4_data).decode("utf-8")
    mock_client.interactions.create.return_value = mock_interaction

    state = PipelineState(
        original_intent="Character animation",
        mode="reference",
        reference_assets_b64=["ref_image_b64"]
    )

    with tempfile.TemporaryDirectory() as output_dir:
        result_state = run_pipeline(state, output_dir=output_dir, client=mock_client)
        assert os.path.exists(result_state.stitched_video_path)

def test_cli_execution_mock():
    cmd = [
        "python3", "src/main.py",
        "--prompt", "A panda skiing",
        "--mode", "i2v_chaining",
        "--help"
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    assert "Multi-Agent Generative Media Pipeline" in res.stdout.decode("utf-8")

def test_evaluate_clip_quality_missing_or_empty_video():
    import asyncio
    from src.agents.stitcher_graph import evaluate_clip_quality

    # 1. Missing file evaluation test
    res_missing = asyncio.run(evaluate_clip_quality(
        shot_index=1,
        prompt="Test shot",
        video_path="/tmp/non_existent_video_path_9999.mp4"
    ))
    assert res_missing["score"] == 0.0
    assert "FAILED" in res_missing["feedback"]

    # 2. Empty 0-byte file evaluation test
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        empty_path = tmp.name

    try:
        res_empty = asyncio.run(evaluate_clip_quality(
            shot_index=2,
            prompt="Empty shot",
            video_path=empty_path
        ))
        assert res_empty["score"] == 0.0
        assert "FAILED" in res_empty["feedback"]
    finally:
        if os.path.exists(empty_path):
            os.remove(empty_path)
