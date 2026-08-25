from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field


class VideoShot(BaseModel):
    shot_index: int
    prompt: str
    spoken_dialogue: Optional[str] = None
    evaluation_criteria: Optional[str] = None
    video_path: Optional[str] = None
    extracted_last_frame_b64: Optional[str] = None
    status: str = "pending"


class StoryboardEntry(BaseModel):
    scene_number: int
    description: str
    camera_angle: str = "medium"
    spoken_dialogue: Optional[str] = None
    evaluation_criteria: Optional[str] = None
    visual_elements: List[str] = Field(default_factory=list)


class PipelineState(BaseModel):
    original_intent: str
    num_shots: int = Field(default=3, ge=1, le=10)
    mode: Literal["reference", "i2v_chaining"] = "i2v_chaining"
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    duration: int = 10
    max_attempts: int = Field(default=2, ge=1, le=5)
    voice_transcript: Optional[str] = None
    reference_assets_b64: List[str] = Field(default_factory=list)
    reference_audio_b64: List[str] = Field(default_factory=list)
    screenplay_draft: Optional[str] = None
    storyboard: List[StoryboardEntry] = Field(default_factory=list)
    shots: List[VideoShot] = Field(default_factory=list)
    stitched_video_path: Optional[str] = None
    quality_rating: Optional[float] = None
    attempt_counter: int = 0
    trajectory_logs: List[Dict[str, Any]] = Field(default_factory=list)

    def log_event(self, agent: str, action: str, details: Dict[str, Any]):
        """Logs an agent interaction event into the execution trajectory."""
        self.trajectory_logs.append({
            "agent": agent,
            "action": action,
            "details": details
        })
