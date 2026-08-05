import os
import tempfile
import base64
from unittest.mock import MagicMock, patch
import cv2
import numpy as np
import pytest
from src.state import PipelineState
from src.agents.stitcher_graph import run_pre_production, run_production_loop, run_pipeline

def create_mock_mp4_bytes():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        path = tmp.name
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(path, fourcc, 10.0, (64, 64))
    for _ in range(5):
        frame = np.full((64, 64, 3), 100, dtype=np.uint8)
        out.write(frame)
    out.release()

    with open(path, "rb") as f:
        data = f.read()
    os.remove(path)
    return data

async def mock_run_adk_agent(agent, prompt, media_parts=None, session_service=None):
    if agent.name == "ScreenwriterAgent":
        return '''[
            {"scene_number": 1, "description": "Red panda walking", "camera_angle": "wide"},
            {"scene_number": 2, "description": "Red panda skiing", "camera_angle": "medium"},
            {"scene_number": 3, "description": "Red panda celebrating", "camera_angle": "close-up"}
        ]'''
    elif agent.name == "PromptOptimizerAgent":
        return "Enhanced cinematic prompt"
    elif agent.name == "HealthCheckerAgent":
        return "APPROVED"
    elif agent.name == "QualityRaterAgent":
        return '{"score": 0.9, "drift_detected": false, "drift_breakdown": {"face_identity_drift": false, "product_drift": false, "clothing_drift": false, "accessories_drift": false, "background_drift": false}, "feedback": "Good quality"}'
    return "OK"

@patch("src.agents.stitcher_graph.run_adk_agent", side_effect=mock_run_adk_agent)
def test_run_pre_production(mock_adk):
    state = PipelineState(original_intent="A red panda skiing in Hakuba", mode="i2v_chaining")
    updated_state = run_pre_production(state)

    assert len(updated_state.storyboard) == 3
    assert len(updated_state.shots) == 3
    assert updated_state.shots[0].prompt == "wide shot: Red panda walking"

@patch("src.agents.stitcher_graph.run_adk_agent", side_effect=mock_run_adk_agent)
def test_run_production_loop_mocked(mock_adk):
    mock_client = MagicMock()
    fake_mp4 = create_mock_mp4_bytes()

    mock_interaction = MagicMock()
    mock_interaction.output_video.data = base64.b64encode(fake_mp4).decode("utf-8")
    mock_client.interactions.create.return_value = mock_interaction

    state = PipelineState(original_intent="Test intent", mode="i2v_chaining")
    state = run_pre_production(state)

    with tempfile.TemporaryDirectory() as tmpdir:
        result_state = run_production_loop(state, output_dir=tmpdir, client=mock_client)
        assert result_state.stitched_video_path is not None
        assert os.path.exists(result_state.stitched_video_path)
        assert len(result_state.shots) == 3
        for shot in result_state.shots:
            assert shot.status == "completed"
            assert os.path.exists(shot.video_path)
