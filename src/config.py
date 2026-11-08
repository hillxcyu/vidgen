import os
from typing import Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# Force Google GenAI SDK and ADK Runner to use Vertex AI ADC mode
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

class Config:
    PROJECT_ID: str = os.getenv("GOOGLE_CLOUD_PROJECT", "vital-octagon-19612")
    LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    ORCHESTRATOR_MODEL: str = os.getenv("ORCHESTRATOR_MODEL", "gemini-3.8-flash")
    VIDEO_GEN_MODEL: str = os.getenv("VIDEO_GEN_MODEL", "gemini-omni-1.2-flash")
    VIDEO_EXTEND_MODEL: str = os.getenv("VIDEO_EXTEND_MODEL", "gemini-omni-1.2-flash")
    VIDEO_EXTEND_FALLBACK_MODEL: str = os.getenv("VIDEO_EXTEND_FALLBACK_MODEL", "gemini-omni-flash-preview")
    VIDEO_EXTEND_INPUT_SECONDS: float = float(os.getenv("VIDEO_EXTEND_INPUT_SECONDS", "5.0"))
    MEDIA_PROCESSING: str = os.getenv("MEDIA_PROCESSING", "agentic")
    ORCHESTRATOR_TIMEOUT_MS: int = int(os.getenv("ORCHESTRATOR_TIMEOUT_MS", "120000"))
    RATER_TIMEOUT_MS: int = int(os.getenv("RATER_TIMEOUT_MS", "240000"))
    VIDEO_GEN_TIMEOUT_MS: int = int(os.getenv("VIDEO_GEN_TIMEOUT_MS", "600000"))
    MAX_PARALLEL_SHOTS: int = int(os.getenv("MAX_PARALLEL_SHOTS", "3"))

def get_genai_client(timeout_ms: Optional[int] = None) -> genai.Client:
    """Initialize and return Google GenAI Client configured for Vertex AI backend."""
    config = Config()
    t_ms = timeout_ms or config.ORCHESTRATOR_TIMEOUT_MS
    return genai.Client(
        vertexai=True,
        project=config.PROJECT_ID,
        location=config.LOCATION,
        http_options=types.HttpOptions(timeout=t_ms),
    )
