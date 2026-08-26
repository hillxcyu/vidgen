# `PLAN.md`

## 📋 Metadata
*   **Task:** Refactor Architecture to ADK `AgentTool` Pattern for 100% Context Cache Alignment
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-26
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Eliminate System Instruction Swapping in Main Session**:
   - Wrap `ScreenwriterAgent`, `StoryboarderAgent`, `PromptOptimizerAgent`, `HealthCheckerAgent`, and `QualityRaterAgent` inside `google.adk.tools.AgentTool`.
   - Register them in `root_agent.tools = [AgentTool(...), generate_video_shot_clip, parse_terminal_frame, concatenate_video_clips]`.
   - Clear `root_agent.sub_agents = []` to eliminate conversational `transfer_to_agent` swaps in the main conversation history.
   - **Result:** The system prompt for `vidgen_orchestrator` remains 100% static and immutable on every turn in the session, guaranteeing full Gemini context cache alignment and eliminating the ADK Dev UI performance alert.

2. **Clean Sub-Agent Role Isolation**:
   - Update instructions for each sub-agent: they now receive requests as tool inputs and return clean, structured responses (screenplays, storyboards, optimized prompts, safety audits, and multimodal video ratings) without needing to issue `transfer_to_agent`.
   - `QualityRaterAgent` retains its `evaluate_video_clip_quality` tool for real multimodal `.mp4` video frame inspection.

3. **Testing & CI/CD**:
   - Update `tests/unit/test_agent.py` to verify `AgentTool` names on `root_agent.tools`.
   - Run unit and integration test suite (`uv run pytest tests/unit tests/integration`).
   - Commit and push to `main` for Cloud Run deployment.
   - Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

4. **Verification**:
   - Verify zero cache warnings, clean tool execution traces, and full multimodal video evaluation.
