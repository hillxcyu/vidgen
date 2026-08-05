import os
import json
import time
import glob
from typing import List, Dict, Any, Optional
from src.config import Config

def get_default_bucket_name() -> str:
    """Returns the default GCS showcase bucket name."""
    env_bucket = os.getenv("GCS_SHOWCASE_BUCKET")
    if env_bucket and env_bucket.strip():
        return env_bucket.strip()
    config = Config()
    project_id = config.PROJECT_ID or "universal-trail-492014-n5"
    return f"{project_id}-vidgen-showcase"

def get_gcs_output_uri(run_id: str, filename: str) -> str:
    """Constructs a direct GCS target URI (gs://<bucket>/showcase/<run_id>/<filename>) for direct model output writing."""
    bucket_name = get_default_bucket_name()
    return f"gs://{bucket_name}/showcase/{run_id}/{filename}"

def gcs_uri_to_https_url(gcs_uri: str) -> str:
    """Converts gs://bucket/path/to/file to https://storage.googleapis.com/bucket/path/to/file."""
    if gcs_uri and gcs_uri.startswith("gs://"):
        parts = gcs_uri[5:].split("/", 1)
        bucket = parts[0]
        blob = parts[1] if len(parts) > 1 else ""
        return f"https://storage.googleapis.com/{bucket}/{blob}"
    return gcs_uri or ""

def get_storage_client() -> Optional[Any]:
    """Returns a Google Cloud Storage client instance or None if unauthenticated/offline."""
    try:
        from google.cloud import storage
        config = Config()
        if config.PROJECT_ID:
            return storage.Client(project=config.PROJECT_ID)
        return storage.Client()
    except Exception as e:
        print(f"[NOTICE] GCS storage client initialization notice: {e}")
        return None

def ensure_gcs_bucket(client: Any, bucket_name: str) -> Optional[Any]:
    """Retrieves or attempts to create the GCS showcase bucket."""
    try:
        bucket = client.bucket(bucket_name)
        if not bucket.exists():
            config = Config()
            location = config.LOCATION if config.LOCATION and config.LOCATION.upper() != "GLOBAL" else "us-central1"
            bucket = client.create_bucket(bucket_name, location=location)
        return bucket
    except Exception as e:
        print(f"[NOTICE] GCS bucket '{bucket_name}' access notice: {e}")
        try:
            return client.get_bucket(bucket_name)
        except Exception:
            return None

def upload_file_to_gcs(bucket: Optional[Any], local_path: str, gcs_blob_name: str) -> Optional[str]:
    """Uploads a local file to GCS and returns its GCS URI or public URL."""
    if not bucket or not os.path.exists(local_path):
        return None
    try:
        blob = bucket.blob(gcs_blob_name)
        blob.upload_from_filename(local_path)
        # Attempt public URL or standard GCS URI
        return f"https://storage.googleapis.com/{bucket.name}/{gcs_blob_name}"
    except Exception as e:
        print(f"[NOTICE] GCS upload failed for {local_path}: {e}")
        return None

def save_run(
    run_id: str,
    original_intent: str,
    num_shots: int,
    mode: str,
    stitched_video_path: Optional[str] = None,
    shots: Optional[List[Dict[str, Any]]] = None,
    trajectory_logs: Optional[List[Dict[str, Any]]] = None,
    voice_transcript: Optional[str] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
    output_dir: str = "output"
) -> Dict[str, Any]:
    """Saves a run to showcase, uploading media files to GCS and updating manifest index."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    bucket_name = get_default_bucket_name()
    client = get_storage_client()
    bucket = ensure_gcs_bucket(client, bucket_name) if client else None

    # Prepare local and GCS paths
    gcs_urls = {}
    
    # 1. Upload stitched video
    if stitched_video_path and os.path.exists(stitched_video_path):
        filename = os.path.basename(stitched_video_path)
        blob_path = f"showcase/{run_id}/{filename}"
        url = upload_file_to_gcs(bucket, stitched_video_path, blob_path)
        if url:
            gcs_urls["stitched_video_url"] = url

    # 2. Upload shot MP4 clips and last frames
    processed_shots = []
    if shots:
        for shot in shots:
            shot_copy = dict(shot)
            s_idx = shot.get("shot_index", 1)
            local_clip = os.path.join(output_dir, f"shot_{s_idx}.mp4")
            local_frame = os.path.join(output_dir, f"shot_{s_idx}_last_frame.png")

            if os.path.exists(local_clip):
                url = upload_file_to_gcs(bucket, local_clip, f"showcase/{run_id}/shot_{s_idx}.mp4")
                if url:
                    shot_copy["gcs_video_url"] = url

            if os.path.exists(local_frame):
                url = upload_file_to_gcs(bucket, local_frame, f"showcase/{run_id}/shot_{s_idx}_last_frame.png")
                if url:
                    shot_copy["gcs_frame_url"] = url

            processed_shots.append(shot_copy)

    run_entry = {
        "run_id": run_id,
        "pinned_at": timestamp,
        "original_intent": original_intent,
        "num_shots": num_shots,
        "mode": mode,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "duration": duration,
        "voice_transcript": voice_transcript,
        "stitched_video_path": stitched_video_path,
        "stitched_video_url": gcs_urls.get("stitched_video_url", f"/output/{os.path.basename(stitched_video_path)}" if stitched_video_path else None),
        "gcs_bucket": bucket.name if bucket else None,
        "gcs_synced": bool(gcs_urls.get("stitched_video_url")),
        "shots": processed_shots,
        "trajectory_logs": trajectory_logs or []
    }

    # Save to local manifest file
    os.makedirs(output_dir, exist_ok=True)
    manifest_path = os.path.join(output_dir, "saved_runs.json")
    saved_runs = get_saved_runs(output_dir)
    # Deduplicate by run_id
    saved_runs = [r for r in saved_runs if r.get("run_id") != run_id]
    saved_runs.insert(0, run_entry)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(saved_runs, f, indent=2)

    # Also upload manifest to GCS if available
    if bucket:
        try:
            blob = bucket.blob(f"showcase/{run_id}/run_manifest.json")
            blob.upload_from_string(json.dumps(run_entry, indent=2), content_type="application/json")
        except Exception:
            pass

    return run_entry

def get_saved_runs(output_dir: str = "output") -> List[Dict[str, Any]]:
    """Returns list of pinned showcase runs from local manifest."""
    manifest_path = os.path.join(output_dir, "saved_runs.json")
    if not os.path.exists(manifest_path):
        return []
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[NOTICE] Error reading saved_runs.json: {e}")
        return []

def delete_saved_run(run_id: str, output_dir: str = "output") -> bool:
    """Removes a run from the pinned showcase manifest."""
    manifest_path = os.path.join(output_dir, "saved_runs.json")
    saved_runs = get_saved_runs(output_dir)
    updated_runs = [r for r in saved_runs if r.get("run_id") != run_id]
    if len(updated_runs) == len(saved_runs):
        return False

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(updated_runs, f, indent=2)
    return True
