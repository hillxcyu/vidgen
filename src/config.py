import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

class Config:
    PROJECT_ID: str = os.getenv("GOOGLE_CLOUD_PROJECT", "universal-trail-492014-n5")
    LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    ORCHESTRATOR_MODEL: str = os.getenv("ORCHESTRATOR_MODEL", "gemini-3.6-flash")
    VIDEO_GEN_MODEL: str = os.getenv("VIDEO_GEN_MODEL", "gemini-omni-flash-preview")

def get_genai_client() -> genai.Client:
    """Initialize and return Google GenAI Client configured for Vertex AI backend."""
    config = Config()
    return genai.Client(
        vertexai=True,
        project=config.PROJECT_ID,
        location=config.LOCATION,
    )
