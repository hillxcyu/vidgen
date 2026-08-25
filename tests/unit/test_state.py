from app.state import PipelineState, VideoShot, StoryboardEntry


def test_pipeline_state_defaults():
    state = PipelineState(original_intent="A red panda skiing in Hakuba")
    assert state.num_shots == 3
    assert state.mode == "i2v_chaining"
    assert state.aspect_ratio == "16:9"
    assert state.resolution == "720p"
    assert state.duration == 10
    assert len(state.trajectory_logs) == 0


def test_pipeline_state_logging():
    state = PipelineState(original_intent="Snowboarder on powder")
    state.log_event("ScreenwriterAgent", "EXPAND_SCRIPT", {"status": "SUCCESS"})
    assert len(state.trajectory_logs) == 1
    assert state.trajectory_logs[0]["agent"] == "ScreenwriterAgent"
    assert state.trajectory_logs[0]["action"] == "EXPAND_SCRIPT"
