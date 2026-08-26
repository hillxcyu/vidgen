# `PLAN.md`

## 📋 Metadata
*   **Task:** Restore Intermediate Step & Sub-Agent Messages in Chat UI
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-26
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Root Cause Analysis**:
   - `root_agent` had `generate_multi_shot_video` (a monolithic all-in-one Python tool) in its tool list. When requested to generate a video, the LLM called this tool directly in one step, executing the entire pipeline silently inside Python and bypassing the 5 ADK sub-agents (`ScreenwriterAgent`, `StoryboarderAgent`, `PromptOptimizerAgent`, `HealthCheckerAgent`, `QualityRaterAgent`).
   - Sub-agent instructions instructed them to return control directly to `vidgen_orchestrator` without mandating visible, user-facing output messages in the chat stream.

2. **Refactor Agent Instructions & Toolset in `app/agent.py`**:
   - Remove `generate_multi_shot_video` from `root_agent.tools` so `root_agent` strictly uses sequential sub-agent delegation (`ScreenwriterAgent` -> `StoryboarderAgent` -> Production Loop: `PromptOptimizerAgent` -> `HealthCheckerAgent` -> `generate_video_shot_clip` -> `QualityRaterAgent` -> `parse_terminal_frame` -> `concatenate_video_clips`).
   - Update instructions for each sub-agent to mandate writing complete, formatted user-facing reports (screenplay draft, storyboard table, optimized prompt with visual rationale, safety audit status, rubric evaluation with scores) directly to the chat before transferring control back.
   - Update `root_agent` instruction to send explicit progress updates at each milestone.

3. **Testing & CI/CD**:
   - Update `tests/unit/test_agent.py` to assert `generate_video_shot_clip` in `root_agent.tools`.
   - Run unit and integration tests (`uv run pytest tests/unit tests/integration`).
   - Commit and push to `main` for Cloud Run.
   - Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

4. **Verification**:
   - Verify multi-agent delegation traces and live reasoning engine stream.
