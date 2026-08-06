# 🎬 vidgen — Feature List & Technical Implementation

This document maintains a comprehensive list of all implemented features in **vidgen**, along with a one-line technical description of how each feature is realized.

---

## 🚀 Core Architecture & Agents

1. **Google ADK 2.0 Multi-Agent Workflow**
   - **Technical Implementation:** Coordinates 7 specialized agents (`Orchestrator`, `Screenwriter`, `Storyboarder`, `PromptOptimizer`, `HealthChecker`, `QualityRater`, `OmniFlash`) built natively using Google ADK `LlmAgent`, `Runner`, and DAG workflow primitives.

2. **Google ADK Session Management & Decoupled Background Execution**
   - **Technical Implementation:** Detaches execution into an `asyncio.Task` bound to ADK `InMemorySessionService`, persisting state snapshots to disk (`output/sessions/*.json`) & GCS for cross-instance Cloud Run recovery on page refresh.

3. **Sequential Image-to-Video (I2V) Prompt Chaining**
   - **Technical Implementation:** Extracts terminal frame (Frame #100) of Shot $N$ using OpenCV as a Base64 image payload to visually anchor Shot $N+1$ in Gemini Omni Flash.

4. **Vertex AI Application Default Credentials (ADC) Engine**
   - **Technical Implementation:** Programmatically sets `GOOGLE_GENAI_USE_VERTEXAI=true` so Google ADK and GenAI SDK authenticate via GCP IAM Service Account without requiring `GEMINI_API_KEY`.

---

## 🎨 Generation & Quality Control

5. **5-Category Major Subject Drift Detection & Quality Rater Feedback Loop**
   - **Technical Implementation:** `QualityRaterAgent` audits Face Identity, Product, Clothing, Props, and Environment ($0.0 - 1.0$ score); scores `< 0.8` trigger feedback re-attempt loops back to `PromptOptimizerAgent`.

6. **Single-Shot Continuous Take Enforcement**
   - **Technical Implementation:** System prompt instructions force `PromptOptimizerAgent` to generate continuous single camera tracking shots while forbidding internal jump cuts or scene switches.

7. **Voice Transcript & Audio Consistency Integration**
   - **Technical Implementation:** Storyboarder and Prompt Optimizer segment spoken transcripts chronologically across scenes, passing voice audio Base64 references to Gemini Omni Flash.

8. **Restricted Shot Duration Selector (5s / 10s)**
   - **Technical Implementation:** Web Studio UI restricts duration selector options to supported 5s and 10s intervals.

---

## 📊 Storage, Cloud & Frontend UI

9. **Showcase Run Pinning & GCS Cloud Storage Sync**
   - **Technical Implementation:** Pinned runs persist stitched MP4s, shot clips, frame PNGs, and JSON manifests to GCS (`gs://...`), querying `showcase/*/run_manifest.json` on GCS to restore saved runs across Cloud Run deployments.

10. **Real-Time Audit Trajectory Visualizer with Folded Communication Cards & Hidden Control Strings**
    - **Technical Implementation:** SSE endpoint streams live agent interactions, running `stripControlString()` on `GeminiOmniFlash` headers and isolating red failure tags (`🔴 FAILED`) strictly to failing agents rather than downstream prompt optimizers receiving feedback.

11. **Asynchronous Non-Blocking Uvicorn Threadpool Offloading**
    - **Technical Implementation:** Synchronous Vertex AI calls, OpenCV frame extractions, FFMPEG concatenations, and GCS storage tasks are offloaded via `await asyncio.to_thread(...)` to prevent blocking FastAPI's async event loop.

---

*Note: Update this document whenever new features or technical components are added to the codebase.*
