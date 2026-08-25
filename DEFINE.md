# `DEFINE.md`

## 📋 Metadata
*   **Stage:** 2 - Problem Decomposition (DEFINE)
*   **Timestamp:** 2026-08-25T10:28:00Z
*   **Target Task:** Update Docs, Commit, Archive Main, Merge, and Deploy Frontend via Cloud Build in `asia-east1`
*   **Status:** Awaiting Confirmation for Stage 3 (ACT)

---

## 📝 Detailed TODO Breakdown

### Phase 1: Documentation & Local Commit [docs] [git]
- [ ] `[T001]` **[docs]** Update `README.md` with ADK 2.0 architecture, `agents-cli` workflow, Agent Runtime deployment (`asia-east1`), and A2A Agent Card specifications.
- [ ] `[T002]` **[git]** Stage all changes (`git add -A`) and commit on branch `adk` with comprehensive commit message.

### Phase 2: Git Branch Archiving & Merging [git]
- [ ] `[T003]` **[git]** Check out `main` branch.
- [ ] `[T004]` **[git]** Create `archive` branch from `main` and push to remote (`git checkout -b archive && git push -u origin archive`).
- [ ] `[T005]` **[git]** Check out `main` and merge `adk` into `main` (`git checkout main && git merge adk`).

### Phase 3: Cloud Build Configuration & Push [cicd] [deploy]
- [ ] `[T006]` **[cicd]** Update `cloudbuild.yaml` with `asia-east1` Artifact Registry (`asia-east1-docker.pkg.dev/$PROJECT_ID/vidgen-repo/vidgen-app:$COMMIT_SHA`) and Cloud Run deploy flags (`--region=asia-east1`, `--port=8080`, environment variables).
- [ ] `[T007]` **[git]** Commit `cloudbuild.yaml` updates to `main`.
- [ ] `[T008]` **[deploy]** Push `main` to `origin/main` (`git push origin main`) to trigger Cloud Build.
- [ ] `[T009]` **[test]** Monitor Cloud Build progress and verify live Cloud Run service endpoint in `asia-east1`.
