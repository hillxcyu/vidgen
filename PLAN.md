# `PLAN.md`

## 📋 Metadata
*   **Task:** Dual UI Routing (`/` for Web Studio, `/adk` for ADK Dev UI), Check `cloudbuild.yaml`, and Implement Explicit Sub-Agent Delegation in Orchestrator
*   **Target Region:** `asia-east1` (Taiwan)
*   **Date:** 2026-08-25
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Verify `cloudbuild.yaml` Configuration**:
   - Confirm `cloudbuild.yaml` targets Artifact Registry and Cloud Run in `asia-east1` with port `8080` and 4Gi memory.

2. **Implement Dual UI Routing in `app/fast_api_app.py`**:
   - Serve our custom Web Studio template (`app/templates/index.html`) at `/`, `/index.html`, and `/studio`.
   - Mount the ADK Angular Dev/Chat UI at `/adk` and `/dev-ui`.

3. **Enable Explicit Sub-Agent Delegation in Orchestrator (`app/agent.py`)**:
   - Refactor `root_agent` and subagents (`ScreenwriterAgent`, `StoryboarderAgent`, `PromptOptimizerAgent`, `HealthCheckerAgent`, `QualityRaterAgent`) to perform visible, step-by-step delegation in the ADK trace.
   - Provide granular tools (`generate_video_shot_clip`, `parse_terminal_frame`, `concatenate_video_clips`) as well as the composite `generate_multi_shot_video` tool.

4. **Testing, Git Push, and Deployment**:
   - Run unit and integration tests (`uv run pytest tests/unit tests/integration`).
   - Commit changes to `main` and push to GitHub to trigger Cloud Build for the Cloud Run frontend.
   - Update Vertex AI Agent Runtime with the new orchestrator delegation logic.

---

## 📋 Proposed Execution Phases

### Phase 1: Dual UI Routing & cloudbuild Verification
* Configure `app/fast_api_app.py` to route `/` to Web Studio and `/adk` to ADK Dev UI.
* Confirm `cloudbuild.yaml` reflects `asia-east1`.

### Phase 2: Orchestrator Sub-Agent Delegation
* Update `app/agent.py` to instruct `root_agent` to delegate to `ScreenwriterAgent` -> `StoryboarderAgent` -> `PromptOptimizerAgent` -> `HealthCheckerAgent` -> generation -> `QualityRaterAgent`.
* Implement modular tools for single shot generation and terminal frame extraction.

### Phase 3: Verification & CI/CD Deployment
* Run test suite `uv run pytest`.
* Commit and push to `origin/main` to deploy Cloud Run frontend via Cloud Build.
* Update Vertex AI Agent Runtime backend.
