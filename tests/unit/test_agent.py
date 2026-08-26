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

    assert screenwriter_agent.name == "ScreenwriterAgent"
    assert storyboarder_agent.name == "StoryboarderAgent"
    assert prompt_optimizer_agent.name == "PromptOptimizerAgent"
    assert health_checker_agent.name == "HealthCheckerAgent"
    assert quality_rater_agent.name == "QualityRaterAgent"


def test_agent_tools():
    tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in root_agent.tools]
    assert "ScreenwriterAgent" in tool_names
    assert "StoryboarderAgent" in tool_names
    assert "PromptOptimizerAgent" in tool_names
    assert "HealthCheckerAgent" in tool_names
    assert "QualityRaterAgent" in tool_names
    assert "generate_video_shot_clip" in tool_names
    assert "parse_terminal_frame" in tool_names
    assert "concatenate_video_clips" in tool_names
