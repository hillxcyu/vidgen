# `PLAN.md`

## 📋 Metadata
*   **Task:** Fix Multi-Agent Orchestration Flow (Enforce PromptOptimizer -> HealthChecker -> `generate_video_shot_clip` Tool -> QualityRater Loop)
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-26
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Fix Sub-Agent Peer Transfer Bypass**:
   - Set `disallow_transfer_to_peers=True` and `disallow_transfer_to_parent=False` on all sub-agents (`ScreenwriterAgent`, `StoryboarderAgent`, `PromptOptimizerAgent`, `HealthCheckerAgent`, `QualityRaterAgent`).
   - Prevents `HealthCheckerAgent` from skipping tool calls and transferring directly to `QualityRaterAgent`.
   - Forces all sub-agents to return control back to `vidgen_orchestrator` after each single sub-task.

2. **Enforce Strict Production Loop in `vidgen_orchestrator`**:
   - Clearly enforce the per-shot sequence in `vidgen_orchestrator` instructions:
     1. Delegate to `PromptOptimizerAgent`.
     2. Delegate to `HealthCheckerAgent`.
     3. **Tool Call:** Execute `generate_video_shot_clip(...)` to render the MP4 clip.
     4. Delegate to `QualityRaterAgent` with the `video_path`.
     5. If score < 0.8 / retry verdict, repeat 1-4 with feedback.
     6. If chaining, call `parse_terminal_frame(...)`.

3. **Testing & Deployment**:
   - Run test suite (`uv run pytest tests/unit tests/integration`).
   - Commit and push to `main` for Cloud Run CI/CD.
   - Update Vertex AI Agent Runtime in `asia-east1`.

4. **Verification**:
   - Verify that sub-agents return control to orchestrator and orchestrator executes the tool before rating.
