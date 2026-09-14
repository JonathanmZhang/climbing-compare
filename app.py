"""Upload endpoint for the climbing comparison pipeline.

Accepts two video uploads, saves them into videos/ under a sanitized
attempt-name stem, then runs the full CLI pipeline on them (extract_pose.py
-> visualize_pose.py -> compute_angles.py per video, then align.py ->
compute_diff.py -> build_viewer_data.py on the pair) so the result is
immediately viewable. Every step is run with its own default flags/paths -
none of this needed explicit arguments once each script's actual defaults
were confirmed to chain together correctly.

Runs on a different origin (port 5000) than the static viewer (port 8000,
served separately via RangeHTTPServer), so CORS is enabled - otherwise the
viewer's JS can make the request but can't read the response.

Usage:
    python app.py
"""

import re
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

SCRIPT_DIR = Path(__file__).resolve().parent
VIDEOS_DIR = Path("videos")
OUTPUT_DIR = Path("output")
# Matches batch_extract.py's VIDEO_EXTENSIONS. Filename-extension check only -
# not deep content validation.
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm"}
# Same character set sanitize_stem() guarantees for names it produces. A name
# coming from an earlier /process response always matches this trivially;
# this exists to reject a malicious name_a/name_b (e.g. "../../etc") in
# /realign's JSON body before it's used to build a filesystem path.
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def sanitize_stem(filename: str) -> str:
    """Derives a safe attempt-name stem from an uploaded filename: strips
    any path/OS-unsafe parts via werkzeug's secure_filename, drops the
    extension, then collapses everything but letters/digits/underscore/
    hyphen into underscores - matching this project's existing attempt_x
    naming convention."""
    safe_name = secure_filename(filename)
    stem = Path(safe_name).stem
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip("_-")
    return stem or "attempt"


def run_step(cmd: list):
    return subprocess.run(cmd, capture_output=True, text=True)


def step_error(step: str, result: subprocess.CompletedProcess):
    return {"error": f"{step} failed", "step": step, "returncode": result.returncode, "stderr": result.stderr}


def process_video(name: str, video_path: Path):
    """Runs extract_pose.py + visualize_pose.py (skipped only if BOTH their
    outputs already exist - a partial cache re-runs both), then
    compute_angles.py (skipped only if its own output already exists), all
    with default flags/paths. Returns None on success, or an error dict from
    step_error() on the first failure."""
    video_output_dir = OUTPUT_DIR / name
    json_path = video_output_dir / f"{name}.json"
    overlay_path = video_output_dir / f"{name}_overlay.mp4"
    angles_path = video_output_dir / f"{name}_angles.json"

    if not (json_path.exists() and overlay_path.exists()):
        result = run_step([sys.executable, str(SCRIPT_DIR / "extract_pose.py"), str(video_path)])
        if result.returncode != 0:
            return step_error("extract_pose.py", result)

        result = run_step([sys.executable, str(SCRIPT_DIR / "visualize_pose.py"), str(video_path)])
        if result.returncode != 0:
            return step_error("visualize_pose.py", result)

    if not angles_path.exists():
        result = run_step([sys.executable, str(SCRIPT_DIR / "compute_angles.py"), str(json_path)])
        if result.returncode != 0:
            return step_error("compute_angles.py", result)

    return None


def parse_optional_float(value, field_name: str):
    """Returns (parsed_value_or_None, error_message_or_None)."""
    if value is None:
        return None, None
    try:
        return float(value), None
    except (TypeError, ValueError):
        return None, f"{field_name} must be a number"


def run_align_chain(name_a: str, name_b: str, angles_a_path: Path, angles_b_path: Path, end_event_a=None, end_event_b=None):
    """Runs align.py -> compute_diff.py -> build_viewer_data.py on an
    already-computed pair of angles JSONs - the shared tail of /process and
    /realign. Returns (body_dict, http_status)."""
    result = run_step([sys.executable, str(SCRIPT_DIR / "align.py"), str(angles_a_path), str(angles_b_path)])
    if result.returncode != 0:
        return step_error("align.py", result), 500

    alignment_path = OUTPUT_DIR / f"{name_a}_vs_{name_b}_alignment.json"

    result = run_step([sys.executable, str(SCRIPT_DIR / "compute_diff.py"), str(alignment_path)])
    if result.returncode != 0:
        return step_error("compute_diff.py", result), 500

    divergence_path = OUTPUT_DIR / f"{name_a}_vs_{name_b}_divergence.json"

    build_cmd = [sys.executable, str(SCRIPT_DIR / "build_viewer_data.py"), str(alignment_path), str(divergence_path)]
    if end_event_a is not None:
        build_cmd += ["--end-event-a", str(end_event_a)]
    if end_event_b is not None:
        build_cmd += ["--end-event-b", str(end_event_b)]

    result = run_step(build_cmd)
    if result.returncode != 0:
        return step_error("build_viewer_data.py", result), 500

    pair_name = f"{name_a}_vs_{name_b}"
    data_path = f"/viewer/data/{pair_name}/data.json"
    return {"pair_name": pair_name, "data_path": data_path, "name_a": name_a, "name_b": name_b}, 200


@app.route("/process", methods=["POST"])
def process():
    if "video_a" not in request.files or "video_b" not in request.files:
        return jsonify({"error": "both video_a and video_b files are required"}), 400

    file_a = request.files["video_a"]
    file_b = request.files["video_b"]

    if not file_a.filename or not file_b.filename:
        return jsonify({"error": "both video_a and video_b must have a filename"}), 400

    name_a = sanitize_stem(file_a.filename)
    name_b = sanitize_stem(file_b.filename)
    ext_a = Path(secure_filename(file_a.filename)).suffix.lower()
    ext_b = Path(secure_filename(file_b.filename)).suffix.lower()

    invalid = [
        (label, ext) for label, ext in (("video_a", ext_a), ("video_b", ext_b)) if ext not in VIDEO_EXTENSIONS
    ]
    if invalid:
        bad = ", ".join(f"{label} ({ext or 'no extension'})" for label, ext in invalid)
        allowed = ", ".join(sorted(VIDEO_EXTENSIONS))
        return jsonify({"error": f"unsupported file extension for {bad} - allowed: {allowed}"}), 400

    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    video_a_path = VIDEOS_DIR / f"{name_a}{ext_a}"
    video_b_path = VIDEOS_DIR / f"{name_b}{ext_b}"
    file_a.save(video_a_path)
    file_b.save(video_b_path)

    for name, video_path in ((name_a, video_a_path), (name_b, video_b_path)):
        error = process_video(name, video_path)
        if error:
            return jsonify(error), 500

    angles_a_path = OUTPUT_DIR / name_a / f"{name_a}_angles.json"
    angles_b_path = OUTPUT_DIR / name_b / f"{name_b}_angles.json"

    body, status = run_align_chain(name_a, name_b, angles_a_path, angles_b_path)
    return jsonify(body), status


@app.route("/realign", methods=["POST"])
def realign():
    payload = request.get_json(silent=True) or {}
    name_a = payload.get("name_a")
    name_b = payload.get("name_b")

    if not (isinstance(name_a, str) and SAFE_NAME_RE.match(name_a)) or not (
        isinstance(name_b, str) and SAFE_NAME_RE.match(name_b)
    ):
        return jsonify(
            {"error": "name_a and name_b are required and must contain only letters, digits, underscore, or hyphen"}
        ), 400

    end_event_a, err_a = parse_optional_float(payload.get("end_event_a"), "end_event_a")
    end_event_b, err_b = parse_optional_float(payload.get("end_event_b"), "end_event_b")
    errors = [e for e in (err_a, err_b) if e]
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    angles_a_path = OUTPUT_DIR / name_a / f"{name_a}_angles.json"
    angles_b_path = OUTPUT_DIR / name_b / f"{name_b}_angles.json"

    missing = [str(p) for p in (angles_a_path, angles_b_path) if not p.exists()]
    if missing:
        return jsonify(
            {
                "error": f"missing angles JSON: {', '.join(missing)} - "
                f"/realign only works after a successful /process run for both names"
            }
        ), 400

    body, status = run_align_chain(name_a, name_b, angles_a_path, angles_b_path, end_event_a, end_event_b)
    return jsonify(body), status


if __name__ == "__main__":
    app.run(port=5000)
