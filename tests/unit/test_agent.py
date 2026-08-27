from app.agent import (
    root_agent,
    app,
    screenwriter_agent,
    storyboarder_agent,
    prompt_optimizer_agent,
    health_checker_agent,
    quality_rater_agent,
)


def test_agent_definitions():
    assert root_agent is not None
    assert root_agent.name == "vidgen_orchestrator"
    assert app is not None
    assert app.name == "vidgen-omni"

    sub_agent_names = [sa.name for sa in root_agent.sub_agents]
    assert "ScreenwriterAgent" in sub_agent_names
    assert "StoryboarderAgent" in sub_agent_names
    assert "PromptOptimizerAgent" in sub_agent_names
    assert "HealthCheckerAgent" in sub_agent_names
    assert "QualityRaterAgent" in sub_agent_names
    assert "Reference Image & Continuity Risk" in health_checker_agent.instruction
    assert "REFERENCE IMAGE ROLE BINDING" in prompt_optimizer_agent.instruction


def test_agent_output_keys_and_callbacks():
    assert screenwriter_agent.output_key == "screenplay"
    assert storyboarder_agent.output_key == "storyboard"
    assert root_agent.before_agent_callback is not None
    assert root_agent.after_agent_callback is not None


def test_agent_tools():
    tool_names = [getattr(t, "__name__", getattr(t, "name", str(t))) for t in root_agent.tools]
    assert "generate_video_shot_clip" in tool_names
    assert "parse_initial_frame" in tool_names
    assert "parse_terminal_frame" in tool_names
    assert "concatenate_video_clips" in tool_names
    assert any("preload_memory" in name.lower() or "memory" in name.lower() for name in tool_names)
    
    # Verify QualityRaterAgent has multimodal inspection tool
    quality_rater_tools = [getattr(t, "__name__", str(t)) for t in quality_rater_agent.tools]
    assert "evaluate_video_clip_quality" in quality_rater_tools


import pytest
import asyncio
from unittest.mock import MagicMock
from app.agent import init_session_state, sync_session_to_memory, parse_initial_frame, parse_terminal_frame


@pytest.mark.asyncio
async def test_init_session_state():
    mock_ctx = MagicMock()
    mock_ctx.state = {}
    await init_session_state(mock_ctx)
    assert mock_ctx.state["pipeline_stage"] == "pre_production"
    assert mock_ctx.state["user:directing_mode"] == "interactive"
    assert mock_ctx.state["user:preferred_aspect_ratio"] == "16:9"
    assert mock_ctx.state["user:preferred_resolution"] == "720p"
    assert mock_ctx.state["user:default_mode"] == "i2v_chaining"
    assert "user:cinematic_style" in mock_ctx.state
    assert "user:character_bible" in mock_ctx.state
    assert mock_ctx.state["app:total_videos_rendered"] == 0
    assert mock_ctx.state["app:total_shots_generated"] == 0


@pytest.mark.asyncio
async def test_sync_session_to_memory():
    mock_ctx = MagicMock()
    mock_ctx.add_session_to_memory = MagicMock()
    await sync_session_to_memory(mock_ctx)


@pytest.mark.asyncio
async def test_evaluate_video_clip_quality_with_reference():
    from app.agent import evaluate_video_clip_quality
    # Test missing file error path
    res = await evaluate_video_clip_quality(
        video_path="/non/existent/video.mp4",
        prompt="A detective walking in the rain",
        reference_image_path="/non/existent/ref.png"
    )
    assert res["score"] == 0.0
    assert res["verdict"] == "RETRY"


@pytest.mark.asyncio
async def test_generate_video_shot_clip_signature():
    from app.agent import generate_video_shot_clip
    import inspect
    sig = inspect.signature(generate_video_shot_clip)
    assert "reference_image_path" in sig.parameters
    assert "input_image_path" in sig.parameters
    assert "end_image_path" in sig.parameters



