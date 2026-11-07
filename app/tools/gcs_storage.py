import os
import json
import time
from typing import List, Dict, Any, Optional
from app.config import Config


def get_default_bucket_name() -> str:
    """Returns the default GCS showcase bucket name."""
    env_bucket = os.getenv("GCS_SHOWCASE_BUCKET")
    if env_bucket and env_bucket.strip():
        return env_bucket.strip()
    config = Config()
    project_id = config.PROJECT_ID or "vital-octagon-19612"
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
    """Retrieves or attempts to create the GCS showcase bucket and ensures public read permissions."""
    if not client or not bucket_name:
        return None
    bucket = client.bucket(bucket_name)
    try:
        if not bucket.exists():
            config = Config()
            location = config.LOCATION if config.LOCATION and config.LOCATION.upper() != "GLOBAL" else "us-central1"
            bucket = client.create_bucket(bucket_name, location=location)
            try:
                policy = bucket.get_iam_policy(requested_policy_version=3)
                has_all_users = any(
                    b.get("role") == "roles/storage.objectViewer" and "allUsers" in b.get("members", [])
                    for b in policy.bindings
                )
                if not has_all_users:
                    policy.bindings.append({"role": "roles/storage.objectViewer", "members": {"allUsers"}})
                    bucket.set_iam_policy(policy)
            except Exception:
                pass
        return bucket
    except Exception as e:
        print(f"[NOTICE] GCS bucket '{bucket_name}' access notice: {e}")
        try:
            return client.get_bucket(bucket_name)
        except Exception:
            # Return unverified bucket handle so object-level uploads (storage.objects.create)
            # succeed even when the runtime service account lacks storage.buckets.get permission.
            return bucket


def upload_file_to_gcs(bucket: Optional[Any], local_path: str, gcs_blob_name: str) -> Optional[str]:
    """Uploads a local file to GCS and returns its GCS URI or public URL."""
    if not bucket or not os.path.exists(local_path):
        return None
    try:
        blob = bucket.blob(gcs_blob_name)
        blob.cache_control = "no-cache, max-age=0"
        blob.upload_from_filename(local_path)
        try:
            blob.make_public()
        except Exception:
            pass
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
    output_dir: str = "output",
    master_quality_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Saves a run to showcase, uploading media files to GCS and updating manifest index."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    bucket_name = get_default_bucket_name()
    client = get_storage_client()
    bucket = ensure_gcs_bucket(client, bucket_name) if client else None

    gcs_urls = {}
    
    if stitched_video_path and os.path.exists(stitched_video_path):
        filename = os.path.basename(stitched_video_path)
        blob_path = f"showcase/{run_id}/{filename}"
        url = upload_file_to_gcs(bucket, stitched_video_path, blob_path)
        if url:
            gcs_urls["stitched_video_url"] = url

    local_anchor = os.path.join(output_dir, "reference_anchor.png")
    if os.path.exists(local_anchor):
        anchor_url = upload_file_to_gcs(bucket, local_anchor, f"showcase/{run_id}/reference_anchor.png")
        if anchor_url:
            gcs_urls["reference_anchor_url"] = anchor_url

    processed_shots = []
    if shots:
        for shot in shots:
            shot_copy = dict(shot)
            s_idx = shot.get("shot_index", 1)
            local_clip = os.path.join(output_dir, f"shot_{s_idx}.mp4")
            local_first_frame = os.path.join(output_dir, f"shot_{s_idx}_first_frame.png")
            local_frame = os.path.join(output_dir, f"shot_{s_idx}_last_frame.png")

            if not shot_copy.get("video_url"):
                shot_copy["video_url"] = f"/output/shot_{s_idx}.mp4"
            if not shot_copy.get("frame_url"):
                shot_copy["frame_url"] = f"/output/shot_{s_idx}_last_frame.png"

            if os.path.exists(local_clip):
                url = upload_file_to_gcs(bucket, local_clip, f"showcase/{run_id}/shot_{s_idx}.mp4")
                if url:
                    shot_copy["gcs_video_url"] = url

            if os.path.exists(local_first_frame):
                f0_url = upload_file_to_gcs(bucket, local_first_frame, f"showcase/{run_id}/shot_{s_idx}_first_frame.png")
                if f0_url:
                    shot_copy["gcs_first_frame_url"] = f0_url

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
        "reference_anchor_url": gcs_urls.get("reference_anchor_url"),
        "gcs_bucket": bucket.name if bucket else None,
        "gcs_synced": bool(gcs_urls.get("stitched_video_url")),
        "shots": processed_shots,
        "master_quality_report": master_quality_report,
        "trajectory_logs": trajectory_logs or []
    }

    manifest_path = os.path.join(output_dir, "saved_runs.json")
    saved_runs = get_saved_runs(output_dir)
    saved_runs = [r for r in saved_runs if r.get("run_id") != run_id]
    saved_runs.insert(0, run_entry)

    try:
        os.makedirs(output_dir, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(saved_runs, f, indent=2)
    except Exception as e:
        print(f"[NOTICE] Local saved_runs.json write notice: {e}")

    if bucket:
        try:
            blob = bucket.blob(f"showcase/{run_id}/run_manifest.json")
            blob.cache_control = "no-cache, max-age=0"
            blob.upload_from_string(json.dumps(run_entry, indent=2), content_type="application/json")
            try:
                blob.make_public()
            except Exception:
                pass
        except Exception:
            pass

    return run_entry


def get_saved_runs(output_dir: str = "output") -> List[Dict[str, Any]]:
    """Returns list of pinned showcase runs, merging local manifest with GCS showcase manifests."""
    runs_by_id: Dict[str, Dict[str, Any]] = {}

    manifest_path = os.path.join(output_dir, "saved_runs.json")
    candidate_local_paths = [manifest_path]
    if output_dir in ("output", "/tmp/vidgen_output", "/app/output"):
        for fallback_p in ("/app/output/saved_runs.json", "output/saved_runs.json"):
            if fallback_p not in candidate_local_paths:
                candidate_local_paths.append(fallback_p)
    for lpath in candidate_local_paths:
        if os.path.exists(lpath):
            try:
                with open(lpath, "r", encoding="utf-8") as f:
                    local_runs = json.load(f)
                    for r in local_runs:
                        if r.get("run_id") and r["run_id"] not in runs_by_id:
                            runs_by_id[r["run_id"]] = r
            except Exception as e:
                print(f"[NOTICE] Error reading local saved_runs.json ({lpath}): {e}")

    try:
        client = get_storage_client()
        if client:
            candidate_buckets = []
            for b_name in [
                get_default_bucket_name(),
                "vital-octagon-19612-vidgen-showcase",
                "universal-trail-492014-n5-vidgen-showcase",
            ]:
                if b_name and b_name not in candidate_buckets:
                    candidate_buckets.append(b_name)
            for b_name in candidate_buckets:
                try:
                    bucket = client.bucket(b_name)
                    blobs = client.list_blobs(bucket, prefix="showcase/")
                    for blob in blobs:
                        if blob.name.endswith("run_manifest.json"):
                            try:
                                content = blob.download_as_text()
                                entry = json.loads(content)
                                run_id = entry.get("run_id")
                                if run_id:
                                    existing = runs_by_id.get(run_id)
                                    if not existing or entry.get("pinned_at", "") >= existing.get("pinned_at", ""):
                                        runs_by_id[run_id] = entry
                            except Exception as manifest_err:
                                print(f"[NOTICE] Error reading GCS manifest {blob.name}: {manifest_err}")
                except Exception as bucket_err:
                    print(f"[NOTICE] Error listing GCS showcase bucket {b_name}: {bucket_err}")
    except Exception as gcs_err:
        print(f"[NOTICE] Error fetching GCS showcase runs: {gcs_err}")

    all_runs = list(runs_by_id.values())
    all_runs.sort(key=lambda r: r.get("pinned_at", r.get("run_id", "")), reverse=True)

    if all_runs:
        try:
            os.makedirs(output_dir, exist_ok=True)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(all_runs, f, indent=2)
        except Exception:
            pass

    return all_runs


def delete_saved_run(run_id: str, output_dir: str = "output") -> bool:
    """Removes a run from the pinned showcase manifest locally and on GCS."""
    manifest_path = os.path.join(output_dir, "saved_runs.json")
    saved_runs = get_saved_runs(output_dir)
    updated_runs = [r for r in saved_runs if r.get("run_id") != run_id]

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(updated_runs, f, indent=2)

    try:
        client = get_storage_client()
        bucket_name = get_default_bucket_name()
        if client:
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(f"showcase/{run_id}/run_manifest.json")
            if blob.exists():
                blob.delete()
    except Exception as e:
        print(f"[NOTICE] Error deleting GCS manifest for {run_id}: {e}")

    return True


def persist_session_state(session_id: str, state_dict: Dict[str, Any], output_dir: str = "output") -> None:
    """Persists session state dict locally and syncs to GCS bucket for cross-instance recovery."""
    if not session_id:
        return
    sessions_dir = os.path.join(output_dir, "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    local_file = os.path.join(sessions_dir, f"{session_id}.json")

    clean_state = {k: v for k, v in state_dict.items() if k not in ["reference_assets_b64", "reference_audio_b64"]}
    try:
        with open(local_file, "w", encoding="utf-8") as f:
            json.dump(clean_state, f, indent=2)
    except Exception as e:
        print(f"[NOTICE] Error writing local session file: {e}")

    try:
        client = get_storage_client()
        bucket_name = get_default_bucket_name()
        if client:
            bucket = ensure_gcs_bucket(client, bucket_name)
            if bucket:
                blob = bucket.blob(f"sessions/{session_id}.json")
                blob.upload_from_string(json.dumps(clean_state, indent=2), content_type="application/json")
    except Exception as gcs_err:
        print(f"[NOTICE] GCS session sync notice: {gcs_err}")


def retrieve_session_state(session_id: str, output_dir: str = "output") -> Optional[Dict[str, Any]]:
    """Retrieves session state dict from local disk or GCS bucket."""
    if not session_id:
        return None

    local_file = os.path.join(output_dir, "sessions", f"{session_id}.json")
    if os.path.exists(local_file):
        try:
            with open(local_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    try:
        client = get_storage_client()
        bucket_name = get_default_bucket_name()
        if client:
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(f"sessions/{session_id}.json")
            if blob.exists():
                content = blob.download_as_text()
                return json.loads(content)
    except Exception as gcs_err:
        print(f"[NOTICE] Error retrieving GCS session: {gcs_err}")

    return None
