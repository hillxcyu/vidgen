# PLAN.md — Add Mode A (`reference` R2V) 30s Showcase Examples & Upgrade 11-Slide Bilingual GTM Decks (Slides 7–11)

## [2026-11-03 15:53 UTC] Stage 1: Confirmed Final Plan (11-Slide Deck Architecture)

### Confirmed Scope & Slide Architecture
- **11-Slide Bilingual Deck Structure (`EN` & `ZH-CN`):**
  - **Slides 1–6:** Cover, Act I (8-Second Wall), Challenges vs. Solutions, Section Break, ADK 2.0 6-Agent Architecture, and Methodology & Benchmark Proof (updated to reflect **9 × 30s** showcase runs across all 3 continuity modes).
  - **Slide 7 (NEW) — Mode A (`mode="reference"`, Shared `#FFFFFF` Canonical R2V) 30s Retail Showcase:** 3 cards (`UC1 Terracotta Alpine Down Jacket`, `UC2 AeroPulse Cobalt Carbon Runner`, `UC3 LuminaDrop Golden Serum`) with `2×2` storyboard strips (`#FFFFFF Anchor` + `Shot 1 R2V` + `Shot 2 R2V` + `Shot 3 R2V`) demonstrating editorial multi-location hard cuts with `0%` `#FFFFFF` lock and `0.95` SKU consistency across all 3 shots.
  - **Slide 8 — Mode B (`mode="i2v_chaining"`, Shot 1 R2V + `<FIRST_FRAME>` I2V) 30s Retail Showcase:** 3 cards with pixel-locked cut MAE metrics (`1.91–3.95`).
  - **Slide 9 — Mode C (`mode="video_extend"`, Shot 1 R2V + `5.0s` Audio-Intact `task="extend"`) 30s Retail Showcase:** 3 cards with seam-locked single-take A/V metrics (`cut_MAE 2.62–7.83`).
  - **Slide 10 (Unified Hub + Comparison + Hybrid Combinations):**
    1. **Fast-Access All-9 Examples Matrix (`3 SKUs × 3 Modes`):** Clickable one-click MP4 buttons for all **9 × 30s retail campaigns** (`UC1 / UC2 / UC3` × `🎨 Mode A R2V | ⚡ Mode B I2V | 🎞️ Mode C Extend`) + Live Web Studio launcher in one place.
    2. **Side-by-Side 3-Method Engineering Comparison Table (`Mode A` vs. `Mode B` vs. `Mode C`):** Conditioning inputs, transition physics, parallel vs. sequential execution, primary sweet spot, and drift/API constraints.
    3. **Hybrid Multi-Mode Combination Patterns Banner/Card:** How directors combine `Mode A + Mode B + Mode C + Dual-Anchor` per shot within a single 30s–60s+ commercial (e.g., *Act-Break Re-Anchoring*: `Mode A R2V` → `Mode C 5s Extend` unbroken 20s take → `Mode A R2V` hard-cut location jump to re-lock `#FFFFFF` SKU fidelity → `Dual-Anchor` surgical mid-spot re-shoot).
  - **Slide 11 — GTM Execution Playbook:** Buyer persona qualification matrix & 2-week customer pilot path (benchmarking all 3 modes + hybrid choreography).

---

### Execution Phases
1. **Phase 1 — Generate 3 × 30s Mode A (`mode="reference"`) Retail Showcase Runs & Sync 9-Run Manifest**
   - Build `scratch/retail_showcase/run_retail_cases_r2v_mode_a.py` to generate `retail_uc1_apparel_r2v_30s`, `retail_uc2_footwear_r2v_30s`, and `retail_uc3_beauty_r2v_30s` where **all 3 shots (`0–10s`, `10–20s`, `20–30s`)** run native `task="reference_to_video"` with `[anchor_b64]` across distinct multi-location retail sets, verified via `detect_r2v_first_frame_lock()` (`white_px <= 25%`, `MAE >= 12.0`).
   - Stitch each 30s master with `80ms` `xfade` + equal-power `acrossfade`, upload to `gs://vital-octagon-19612-vidgen-showcase/showcase/`, and pin all **9 showcase runs** (`3 Mode C` + `3 Mode B` + `3 Mode A`) in `output/saved_runs.json` and GCS `saved_runs.json`.
2. **Phase 2 — Web Studio Badge Polish & Cloud Run Redeployment (`vidgen-frontend`)**
   - Ensure distinct color-coded Showcase Drawer badges for all 3 modes (`🎨 Mode A: R2V`, `⚡ Mode B: I2V`, `🎞️ Mode C: Video Extend`) in `app/templates/index.html` and `src/templates/index.html`, run `uv run pytest tests/unit tests/integration`, and deploy `vidgen-frontend` on Cloud Run (`vital-octagon-19612`, `asia-east1`) with the 9-run seed manifest.
3. **Phase 3 — Mode A Composites, 11-Slide Bilingual Deck Build & Active Vision Audit (`audit_v11/`)**
   - Generate bilingual `2×2` Mode A storyboard strips (`uc{1,2,3}_r2v_strip_{en,zh}.png`) and sync to GCS.
   - Rebuild both **EN (`1b5jlgCWk3Q2LFr5tDYAZZps6Pw_N2_EaIfbAwk9M_3A`)** and **ZH-CN (`12zy4XxPt7sllLsNF3nMIroPRhZSvCGsdEW3UwKnAdj0`)** to the cohesive 11-slide layout (`v11_` element IDs, updated `01 / 11 .. 11 / 11` footers and tripartite speaker notes).
   - Export PDFs/PNGs (`audit_v11/`) and visually inspect Slides 7, 8, 9, 10, and 11 in both EN and ZH-CN to guarantee zero text overflow, crisp alignment, and working links.
