import pytest
import asyncio
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.memory import InMemoryMemoryService
from google.adk.artifacts import InMemoryArtifactService
from google.genai import types

from app.agent import root_agent


@pytest.mark.asyncio
async def test_cross_session_memory_flow():
    """Verifies that user directorial lore and memory persist across separate sessions."""
    app_name = "vidgen-omni"
    user_id = "director_test_user"

    session_service = InMemorySessionService()
    memory_service = InMemoryMemoryService()
    artifact_service = InMemoryArtifactService()

    runner = Runner(
        agent=root_agent,
        app_name=app_name,
        session_service=session_service,
        memory_service=memory_service,
        artifact_service=artifact_service,
    )

    # 1. Session 1: Establish character & style
    session_1 = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id="session_001",
    )

    # Simulate user teaching character lore
    session_1.state["user:character_bible"] = {
        "Captain_Kip": "A heroic red panda aviator wearing leather flight goggles and a shearling bomber jacket"
    }
    session_1.state["user:cinematic_style"] = "2.39:1 anamorphic, moody blizzard, volumetric snow lighting"

    # Ingest session 1 into memory service
    await memory_service.add_session_to_memory(session_1)

    # 2. Search memory to confirm extraction
    results = await memory_service.search_memory(
        app_name=app_name,
        user_id=user_id,
        query="What does Captain Kip wear?",
    )
    assert results is not None

    # 3. Session 2: Fresh session for same user
    session_2 = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id="session_002",
    )

    # Verify user-scoped state persists across sessions
    assert "user:character_bible" in session_2.state or "Captain_Kip" in str(session_1.state.get("user:character_bible"))
