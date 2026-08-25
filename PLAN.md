# `PLAN.md`

## 📋 Metadata
*   **Task:** Commit ADK 2.0 Video Generation Pipeline, Archive Original Main, Merge to Main, Update Documentation, and Deploy via Cloud Build in `asia-east1`
*   **Target GCP Project:** `universal-trail-492014-n5`
*   **Target Region:** `asia-east1` (Taiwan)
*   **Date:** 2026-08-25
*   **Status:** Awaiting User Approval (Stage 1: PLAN)

---

## 🎯 Objectives & Scope

1. **Update Documentation**:
   - Update `README.md` to document ADK 2.0 architecture, Vertex AI Agent Runtime in `asia-east1`, `agents-cli` commands (`playground`, `eval`, `deploy`, `publish`), A2A agent card endpoints, and Cloud Run CI/CD.

2. **Commit Working Changes**:
   - Stage all pipeline updates, tests, manifests, and documentation on branch `adk`.
   - Create a comprehensive commit following repository contributing guidelines.

3. **Branch Archival & Merging**:
   - Check out `main`.
   - Create and push `archive` branch from current `main` (`git checkout -b archive && git push -u origin archive`).
   - Merge `adk` into `main` (`git checkout main && git merge adk`).

4. **Configure `cloudbuild.yaml` for `asia-east1`**:
   - Update Artifact Registry target to `asia-east1-docker.pkg.dev/$PROJECT_ID/vidgen-repo/vidgen-app:$COMMIT_SHA`.
   - Update Cloud Run deployment step to `--region=asia-east1`, `--port=8080`, and environment variables `GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_VERTEXAI=true`.
   - Commit `cloudbuild.yaml` updates to `main`.

5. **Push & Trigger Cloud Build**:
   - Push `main` to GitHub (`git push origin main`).
   - Monitor Cloud Build trigger and verify Cloud Run frontend deployment in `asia-east1`.

---

## 📋 Proposed Execution Phases

### Phase 1: Documentation & Pre-Commit Updates
* Update `README.md` with complete ADK 2.0, Agent Runtime, and A2A guide.
* `git add -A` and commit on `adk`.

### Phase 2: Git Branch Archiving & Merging
* Create and push `archive` branch from current `main`.
* Merge `adk` branch into `main`.

### Phase 3: Cloud Build Configuration & Push
* Update `cloudbuild.yaml` for `asia-east1` Artifact Registry & Cloud Run.
* Commit and push `main` to trigger automated Cloud Build.
* Monitor build and verify live Cloud Run service in `asia-east1`.
