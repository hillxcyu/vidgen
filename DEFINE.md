# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-25T11:31:00Z
*   **Target Task:** Dual UI Routing, Orchestrator Sub-Agent Delegation, and Deploy to `asia-east1`
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Dual UI Routing in FastAPI [frontend] [backend]
- [ ] `[T001]` **[backend]** Update `app/fast_api_app.py` to route `/` and `/index.html` to our custom Web Studio UI, and mount ADK's Angular Debug & Chat UI at `/adk` and `/dev-ui`.

### Phase 2: Orchestrator Sub-Agent Delegation [agent] [tools]
- [ ] `[T002]` **[tools]** Add modular single-shot generation tool `generate_video_shot_clip` in `app/agent.py` to support step-by-step clip generation.
- [ ] `[T003]` **[agent]** Update `root_agent` and subagents (`ScreenwriterAgent`, `StoryboarderAgent`, `PromptOptimizerAgent`, `HealthCheckerAgent`, `QualityRaterAgent`) instructions in `app/agent.py` to support interactive step-by-step delegation.

### Phase 3: Testing & CI/CD Deployment [test] [deploy]
- [ ] `[T004]` **[test]** Run `uv run pytest tests/unit tests/integration` to verify all tests pass.
- [ ] `[T005]` **[git]** Commit changes to `main` with detailed commit message and push to GitHub.
- [ ] `[T006]` **[deploy]** Monitor Cloud Build build in `asia-east1` and verify live Cloud Run frontend at `/` (Studio) and `/adk` (ADK UI).
- [ ] `[T007]` **[deploy]** Deploy / update Vertex AI Agent Runtime in `asia-east1` with updated sub-agent delegation.
