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
    ORCHESTRATOR_MODEL: str = os.getenv("ORCHESTRATOR_MODEL", "gemini-3.7-flash")
    VIDEO_GEN_MODEL: str = os.getenv("VIDEO_GEN_MODEL", "gemini-omni-1.1-flash-preview")
    ORCHESTRATOR_TIMEOUT_MS: int = int(os.getenv("ORCHESTRATOR_TIMEOUT_MS", "60000"))
    VIDEO_GEN_TIMEOUT_MS: int = int(os.getenv("VIDEO_GEN_TIMEOUT_MS", "600000"))

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
