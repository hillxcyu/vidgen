# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-26T04:45:30Z
*   **Target Task:** Fix Multi-Agent Orchestration Flow (`PromptOptimizer` -> `HealthChecker` -> `generate_video_shot_clip` -> `QualityRater`)
*   **Status:** IN_PROGRESS (Stage 3: ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Sub-Agent & Orchestrator Configuration [agent] [orchestration]
- [ ] `[T001]` **[agent]** Configure `disallow_transfer_to_peers=True` and `disallow_transfer_to_parent=False` on all sub-agents in `app/agent.py`.
- [ ] `[T002]` **[agent]** Update instructions in `app/agent.py` to enforce strict sequential execution (`PromptOptimizer` -> `HealthChecker` -> `generate_video_shot_clip` tool -> `QualityRater` -> Retry Loop).

### Phase 2: Testing & CI/CD [test] [deploy]
- [ ] `[T003]` **[test]** Run test suite (`uv run pytest tests/unit tests/integration`).
- [ ] `[T004]` **[git]** Commit changes on `main` and push to GitHub (triggers Cloud Run Cloud Build).
- [ ] `[T005]` **[deploy]** Update Vertex AI Agent Runtime in `asia-east1` via `agents-cli deploy`.

### Phase 3: Verification [verify]
- [ ] `[T006]` **[verify]** Verify live reasoning engine stream query confirms correct orchestration flow.
