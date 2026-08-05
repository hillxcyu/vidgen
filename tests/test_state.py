from src.state import PipelineState, VideoShot, StoryboardEntry

def test_pipeline_state_creation():
    state = PipelineState(
        original_intent="A sci-fi short video",
        mode="i2v_chaining"
    )
    assert state.original_intent == "A sci-fi short video"
    assert state.mode == "i2v_chaining"
    assert len(state.shots) == 0
    assert state.attempt_counter == 0

def test_pipeline_state_with_shots():
    shot = VideoShot(shot_index=1, prompt="Shot 1 prompt")
    sb = StoryboardEntry(scene_number=1, description="Opening scene", camera_angle="wide")
    state = PipelineState(
        original_intent="Test",
        mode="reference",
        storyboard=[sb],
        shots=[shot]
    )
    assert len(state.storyboard) == 1
    assert len(state.shots) == 1
    assert state.shots[0].prompt == "Shot 1 prompt"
