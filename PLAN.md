# `PLAN.md`

## 📋 Metadata
*   **Task:** Restore Conversational Sub-Agents with Unified Cache-Aligned System Instruction
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-26
*   **Status:** IN_PROGRESS (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Restore Visible Chat Messages from All Sub-Agents**:
   - Return to conversational sub-agent hierarchy (`root_agent.sub_agents = [ScreenwriterAgent, StoryboarderAgent, PromptOptimizerAgent, HealthCheckerAgent, QualityRaterAgent]`).
   - Every sub-agent is an active conversational participant emitting top-level Assistant Message Events directly in the chat stream.

2. **Context Cache Alignment via Unified Base Instruction**:
   - Establish a shared, static `UNIFIED_BASE_SYSTEM_INSTRUCTION` prefix defining the entire multi-agent system, roles, and rules across all 6 agents (`root_agent` and the 5 sub-agents).
   - This shared prefix maximizes Gemini Context Caching prefix reuse across agent transfers.

3. **Retain Multimodal Video Evaluation Tool on `QualityRaterAgent`**:
   - `QualityRaterAgent` keeps `evaluate_video_clip_quality` to inspect the actual `.mp4` video frames and outputs the score, rubric breakdown, and visual critique to the user.

4. **Testing & CI/CD**:
   - Update `tests/unit/test_agent.py` to assert sub-agents and tools.
   - Run unit and integration tests (`uv run pytest tests/unit tests/integration`).
   - Commit & push to `main` for Cloud Run Cloud Build.
   - Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

5. **Verification**:
   - Verify visible intermediate messages in chat and live deployment status.
