# `PLAN.md`

## 📋 Metadata
*   **Task:** Add Reference Image Continuity & Diffusion Risk Auditing to HealthCheckerAgent
*   **Target Region:** `asia-east1`
*   **Date:** 2026-08-27
*   **Status:** IN_PROGRESS

---

## 🎯 Objectives & Scope

### 1. Upgrade `HealthCheckerAgent` in `app/agent.py`
- [ ] Add explicit **Reference Image & Continuity Risk Auditing** to `HealthCheckerAgent`.
- [ ] Audit candidate prompts for:
  1. **Diffusion Drift Hazards**: Competing physical text descriptions (e.g. conflicting hair color, facial traits, clothing colors) that risk overriding the reference image in Omni Flash.
  2. **Continuity Discrepancies**: Unmotivated wardrobe, accessory, or aesthetic shifts between consecutive shots.
  3. **Single-Shot Take Integrity**: Absence of internal camera cuts, transitions, or montages within a single 10-second take.
  4. **Content Safety**: Standard policy and safety guardrails.
- [ ] Mandate clear structured reporting in the chat stream:
  - Safety Verdict (`APPROVED` / `REJECTED`)
  - Reference & Continuity Risk (`CLEAR` / `CONTINUITY_RISK_DETECTED`)
  - Motion Feasibility & Pacing (`VERIFIED`)

### 2. Update Prompt Templates & Unit Tests
- [ ] Update `app/prompts/prod_loop_system.txt` with the enhanced Health Checker audit specification.
- [ ] Update unit tests in `tests/unit/test_prompts.py` and `tests/unit/test_agent.py`.

### 3. Automated Verification, Git & Deployment
- [ ] Run full test suite: `uv run pytest tests/unit tests/integration`.
- [ ] Deploy updated agent to Vertex AI Agent Runtime in `asia-east1` (`agents-cli deploy`).
- [ ] Commit and push changes to `main` on GitHub.
