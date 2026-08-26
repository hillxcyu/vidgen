# `PLAN.md`

## 📋 Metadata
*   **Task:** Refactor Architecture to ADK `AgentTool` Pattern for 100% Context Cache Alignment
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-26
*   **Status:** ✅ ALL_TASKS_COMPLETED

---

## 🎯 Objectives & Scope

1. **Eliminate System Instruction Swapping in Main Session**:
   - [x] Wrapped `ScreenwriterAgent`, `StoryboarderAgent`, `PromptOptimizerAgent`, `HealthCheckerAgent`, and `QualityRaterAgent` inside `google.adk.tools.AgentTool`.
   - [x] Registered in `root_agent.tools` and cleared `root_agent.sub_agents = []`.
   - [x] Result: Fixed system instruction for `vidgen_orchestrator`, ensuring 100% context cache alignment and eliminating performance warnings.

2. **Clean Sub-Agent Role Isolation**:
   - [x] Streamlined sub-agent instructions for tool-call execution.
   - [x] Retained `evaluate_video_clip_quality` on `QualityRaterAgent` for multimodal video frame auditing.

3. **Testing & Deployment**:
   - [x] 23/23 unit and integration tests passed.
   - [x] Deployed to Cloud Run via Cloud Build.
   - [x] Deployed to Vertex AI Agent Runtime in `asia-east1`.

4. **Verification**:
   - [x] Verified deployment success on both Agent Runtime and Cloud Run.
