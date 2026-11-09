# Pre-Structured Storyboard JSON Schema & Continuity Choreography

Pass `--storyboard-json path/to/storyboard.json` to `scripts/run_vidgen_workflow.py` whenever you want deterministic control over per-shot framing, spoken dialogue, quality criteria, or `mode="hybrid"` act-break transitions.

---

## 1. JSON Schema (`List[StoryboardEntrySpec]`)

`storyboard.json` is a JSON array of shot objects (`1..N`):

```json
[
  {
    "scene_number": 1,
    "description": "An East Asian woman in a terracotta linen trench coat walks briskly along a sunlit Parisian limestone colonnade, golden morning light catching the fabric drape.",
    "camera_angle": "smooth medium tracking",
    "evaluation_criteria": "Verify exact terracotta trench coat lapel, button count, and belt buckle match the #FFFFFF reference anchor; zero white studio background echo on Frame 0.",
    "spoken_dialogue": "Tailored linen designed to move effortlessly through morning light.",
    "mode_override": "reference"
  },
  {
    "scene_number": 2,
    "description": "Continuing seamlessly down the same sunlit colonnade, she turns slightly toward camera as the breeze lifts the trench hem in one unbroken single-take tracking shot.",
    "camera_angle": "continuous medium close-up dolly",
    "evaluation_criteria": "Seamless continuation from Shot 1's terminal frame with zero jump cuts, identical limestone colonnade lighting, and matching voice timbre.",
    "spoken_dialogue": "Breathable structure meets timeless modern craft.",
    "mode_override": "video_extend"
  },
  {
    "scene_number": 3,
    "description": "Inside a warm minimalist architectural loft with travertine shelving, she pauses beside a sunlit floor-to-ceiling window showcasing the full terracotta trench silhouette.",
    "camera_angle": "slow cinematic push-in",
    "evaluation_criteria": "Clean act-break scene opening in the loft while re-locking exact garment color, texture, and facial identity to the #FFFFFF reference anchor.",
    "spoken_dialogue": "Crafted for every chapter of your day.",
    "mode_override": "reference"
  }
]
```

### Field Reference
| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `scene_number` | `int` | Yes | `1`-based shot index (`1`, `2`, `3`, ...). |
| `description` | `str` | Yes | Visual setting, subject action, lighting, and material detail. Keep to **one continuous camera movement** with zero internal scene cuts. |
| `camera_angle` | `str` | Yes | Camera motion descriptor (e.g., `"smooth medium tracking"`, `"slow macro push-in"`, `"continuous orbital dolly"`). |
| `evaluation_criteria` | `str` | Yes | Shot-specific checklist passed to Auto-Rater v2 (`gemini-3.8-flash` AVU). |
| `spoken_dialogue` | `str \| null` | No | Verbatim spoken line (`<= 12` words for a `10s` clip so speech finishes cleanly before `8.0s`). Omit or set `null` for ambient/instrumental audio. |
| `mode_override` | `str \| null` | No | Per-shot override (`"reference"`, `"i2v_chaining"`, or `"video_extend"`). Used when `--mode hybrid` choreographs multi-act commercials. |

---

## 2. Prompting & Continuity Rules by Mode

### Mode A (`reference` — Parallel `#FFFFFF` Reference-to-Video)
- **Best for:** Multi-location brand montages (e.g., street -> studio -> rooftop) where every shot shares the same hero person or product SKU.
- **Anchor prep:** Isolate the subject/SKU on a clean `#FFFFFF` studio background. In 60-clip benchmarks, `#FFFFFF` isolation + `task="reference_to_video"` raised complex garment/SKU lock from `0.45` to `0.95` with zero relighting halos.
- **Stitching:** `run_vidgen_workflow.py` automatically uses `0.0s` hard-cuts (`--crossfade 0.0`) when all shots are `reference` to avoid `80ms` cross-dissolve pose ghosting across disparate locations.

### Mode B (`i2v_chaining` — Shot 1 R2V + Shots 2..N `<FIRST_FRAME>`)
- **Best for:** Controlled camera progressions where Shot `k` begins from the exact pixel state of Shot `k-1`'s extracted `last_frame.png`.
- **Critical tag rule:** `omni_direct.py` automatically strips `reference_images_b64` (`# References`) and `"Character A"` tags whenever `<FIRST_FRAME>` is attached. Combining `# References` and `<FIRST_FRAME>` causes Omni to prioritize R2V and ignore the starting frame (`MAE` jumps from `~2.5` to `55–99`).

### Mode C (`video_extend` — Shot 1 R2V + Shots 2..N `5.0s` Audio-Intact `task="extend"`)
- **Best for:** Unbroken `20s–30s` single-take hero commercials with continuous motion momentum, room tone, musical bed, and speaker voice timbre.
- **Physical space constraint:** Shots `2..N` **must** remain inside the **same physical room/environment** as Shot `k-1`. Requesting a new location during `task="extend"` forces an abrupt post-seam jump-cut (`peak_early_mae > 28.0`), which `detect_seam_jump_cut()` penalizes and retries.
- **TPVG speech guardrail:** Avoid aggressive brand-endorsement slogans (e.g., `"Buy BrandX today!"`) in spoken lines on person clips to prevent TPVG endorsement takedowns; use descriptive storytelling copy (`<= 12` words/shot).

### Mode D (`hybrid` — Per-Shot `mode_override`)
- Combine `video_extend` for unbroken within-scene motion (e.g., Shot 1 `reference` -> Shot 2 `video_extend`) with `reference` on act-break location changes (e.g., Shot 3 `reference` re-anchoring on `#FFFFFF` in a new setting).

---

## 3. Hierarchical Multi-Scene Schema (`--scenes-json` for `60s–120s+` Videos)

For `60s–90s+` multi-scene commercials, pass `--scenes-json path/to/scenes_storyboard.json`. Each scene runs its own `3 × 10s = 30s` sequence (`Shot 1` R2V with `[hero_anchor.png, scene_i_ref.png]` -> `Shots 2..3` `video_extend`), runs Auto-Rater v2 + Scene Seam Critic (`gemini-3.8-flash` AVU), repairs any `< 0.80` shot via `<FIRST_FRAME> + <LAST_FRAME>` interpolation (`gemini-omni-1.2-flash`), and stitches `output_master_90s.mp4`:

```json
{
  "original_intent": "90s 3-scene luxury botanical serum commercial from morning sanctuary to golden-hour terrace",
  "scenes": [
    {
      "scene_id": "scene_1",
      "title": "Morning Sanctuary: Sunlit Travertine Bathroom",
      "mode": "video_extend",
      "reference_paths": [
        "output/beauty_90s/refs/uc3_beauty_anchor.png",
        "output/beauty_90s/refs/scene1_travertine_sanctuary_ref.png"
      ],
      "shots": [
        {
          "scene_number": 1,
          "description": "Spokesperson stands beside sunlit travertine vanity releasing one golden drop from the amber serum bottle.",
          "camera_angle": "smooth medium close-up",
          "evaluation_criteria": "Verify exact spokesperson, satin blazer, and amber serum bottle in sunlit travertine bathroom; zero white studio backdrop.",
          "spoken_dialogue": "Every morning begins with one luminous golden drop."
        },
        {
          "scene_number": 2,
          "description": "Continuous slow push-in inside the travertine bathroom as she warms the golden oil on her fingertips.",
          "camera_angle": "continuous close-up push-in",
          "evaluation_criteria": "Seamless single-take continuation from Shot 1 inside the exact travertine bathroom.",
          "spoken_dialogue": "Silky botanicals melt weightlessly into morning light."
        },
        {
          "scene_number": 3,
          "description": "Smooth orbital close-up as she holds the amber bottle beside her radiant cheek.",
          "camera_angle": "smooth orbital close-up",
          "evaluation_criteria": "Unbroken single-take motion, exact bottle & garment lock, clean speech finish before 8s.",
          "spoken_dialogue": "Pure hydration that awakens natural skin clarity."
        }
      ]
    }
  ]
}
```


---

## 4. Draft Mode (`--draft-mode`: `360p` Draft → Agentic Loop → Standalone Upscale)

When iterating on multi-shot or `90s+` multi-scene commercials, pass `--draft-mode` (`--draft-resolution 360p --resolution 720p` or `1080p`) to `scripts/run_vidgen_workflow.py`:
- **Candidate Drafting & Closed-Loop QA at `360p` (`$0.02/s`):** All `reference_to_video`, `image_to_video`, `extend`, and `<FIRST_FRAME> + <LAST_FRAME>` interpolation candidates execute on the fast `360p` LDM (`$0.20` per `10s` take), and failed takes (`< 0.80` on `gemini-3.8-flash` AVU) are discarded cheaply.
- **Concurrent Zero-Reasoning Promotion (`task="upscale"`):** Once a scene's `10s` prefix-trimmed shots pass the Agentic Loop, `_upscale_manifest_shots_async` archives `shot_k_draft_360p.mp4` and upscales all winning `10s` clips in parallel (`--max-parallel-upscales 3`, `total_input_tokens: 0`, `2,896` output tok/s for `360p -> 720p`, `5,792` tok/s for `360p -> 1080p`) before `80ms` scene and master stitching.
- **Supported Resolution Pairs:** `360p -> 720p | 1080p` and `720p -> 1080p | 4k` (`<= 15s` per clip; single-hop `360p -> 4k` is rejected upfront by `validate_upscale_transition`).
