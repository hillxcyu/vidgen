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


def test_agent_tools():
    tool_names = [getattr(t, "__name__", str(t)) for t in root_agent.tools]
    assert "generate_video_shot_clip" in tool_names
    assert "parse_initial_frame" in tool_names
    assert "parse_terminal_frame" in tool_names
    assert "concatenate_video_clips" in tool_names
    
    # Verify QualityRaterAgent has multimodal inspection tool
    quality_rater_tools = [getattr(t, "__name__", str(t)) for t in quality_rater_agent.tools]
    assert "evaluate_video_clip_quality" in quality_rater_tools
