from src.config import Config, get_genai_client

def test_config_defaults():
    config = Config()
    assert config.PROJECT_ID is not None
    assert config.LOCATION == "global"
    assert config.ORCHESTRATOR_MODEL == "gemini-3.6-flash"
    assert config.VIDEO_GEN_MODEL == "gemini-omni-flash-preview"

def test_genai_client_init():
    client = get_genai_client()
    assert client is not None
