# Author:Hill YU(xcyu@)
"""Builds and deploys final HTML benchmark report comparing Omni Flash 1.1 reference adherence.
Contains real metrics, prompt logs, and observations from Gemini 3.7 Flash quality audit.
"""

from scripts.run_benchmark import build_html_report, deploy_to_x20

opt_meta = {
    "control_string": "[# References <IMAGE_REF_0>[Character A]image_0.png] [aspect_ratio=16:9] [resolution=720p] [duration=5s] Character A, continuous single take, dynamic cinematic tracking shot following the character skiing gracefully down a powdery slope on Hakuba Happo-One ridge, crisp alpine morning sunlight reflecting off the snow, dramatic Japanese Northern Alps in the background, sharp cinematic focus, photorealistic.",
    "generation_time_s": 40.21
}

smp_meta = {
    "control_string": "[aspect_ratio=16:9] [resolution=720p] [duration=5s] xcyu (reference image) skiing in Hakuba",
    "generation_time_s": 27.61
}

eval_opt = {
    "facial_similarity_score": 0.90,
    "outfit_consistency_score": 0.95,
    "motion_naturalness_score": 0.92,
    "overall_score": 0.92,
    "verdict": "STRONG_ADHERENCE",
    "detailed_critique": "The generated video demonstrates exceptional fidelity to the reference image across all audited categories. The character's facial structure, East Asian ethnicity, age, and dark beanie are well preserved across dynamic action angles. The outfit replication is nearly flawless, faithfully capturing the two-tone red and black technical jacket color-blocking, inner layer, and gear down to gloves and matching ski equipment. The skiing mechanics are fluid and realistic, showing natural carving turns, weight shifts, accurate ski-pole positioning, believable snow spray dynamics, and an authentic alpine backdrop fitting Hakuba Happo-One."
}

eval_smp = {
    "facial_similarity_score": 0.96,
    "outfit_consistency_score": 0.97,
    "motion_naturalness_score": 0.94,
    "overall_score": 0.96,
    "verdict": "STRONG_ADHERENCE",
    "detailed_critique": "The generated video demonstrates exceptional adherence to the reference image across identity, wardrobe, and action. Keyframe 1 matches the subject's facial features, smile, hair, and ribbed beanie with extreme precision. The technical ski jacket is replicated with high fidelity, maintaining accurate paneling, zip details, and color blocking throughout all shots. Subsequent keyframes exhibit natural dynamic skiing mechanics, believable body positioning, realistic snow spray physics, and seamless continuity."
}

if __name__ == "__main__":
    build_html_report(opt_meta, smp_meta, eval_opt, eval_smp)
    deploy_to_x20()
