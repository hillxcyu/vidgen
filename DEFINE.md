# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-27T09:12:30Z
*   **Target Task:** HealthCheckerAgent Reference Image & Continuity Risk Auditing
*   **Status:** IN_PROGRESS

---

## 📝 Detailed TODO Breakdown

### Phase 1: HealthChecker Instructions & Guardrail Upgrade [agent] [safety]
- [ ] `[T001]` **[agent]** Update `health_checker_agent` instruction in `app/agent.py` to audit for reference image conflicts, diffusion text drift, wardrobe shifts, and single-shot take integrity.
- [ ] `[T002]` **[agent]** Update `app/prompts/prod_loop_system.txt` with reference risk guardrails.

### Phase 2: Testing & Verification [test]
- [ ] `[T003]` **[test]** Update `tests/unit/test_prompts.py` to verify HealthChecker reference risk audit strings.
- [ ] `[T004]` **[test]** Run full test suite (`uv run pytest tests/unit tests/integration`).

### Phase 3: Deployment & Git [deploy] [git]
- [ ] `[T005]` **[deploy]** Deploy agent update to Vertex AI Agent Runtime in `asia-east1`.
- [ ] `[T006]` **[git]** Commit all changes and push to `main` on GitHub.
