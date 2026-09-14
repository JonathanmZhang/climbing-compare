"""Build a single viewer-ready data.json (plus peak-divergence screenshots)
for one attempt pair, from an align.py alignment JSON and its matching
compute_diff.py divergence JSON.

Reconstructs the FULL alignment path (not just compute_diff.py's
stall-excised steps) so the viewer can scrub/play through both videos'
entire footage, while still labeling stall and "attempt ended" regions on
the divergence graph. Summary stats and the peak-divergence moment (used
for screenshot extraction) are computed only over "normal" steps, so a
DTW stall or a post-fall divergence spike can't distort them.

Also extracts every frame of both overlay videos as downscaled JPEGs
(viewer/frames/<label>/000000.jpg, ...) for the viewer to render via
canvas+drawImage rather than a <video> element. This replaces an earlier
<video>-based approach: seeking a compressed video's .currentTime on
nearly every DTW path step turned out to be the actual bottleneck behind
viewer lag (codec seek latency), which downscaling/re-encoding the video
couldn't fix. Frame extraction is per-attempt (not per-pair) and skipped
if already done, so the same attempt appearing in multiple pairs isn't
re-extracted.

Usage:
    python build_viewer_data.py output/attempt_f_vs_attempt_g_alignment.json \\
        output/attempt_f_vs_attempt_g_divergence.json --end-event-a 18.5
"""

import argparse
import json
import shutil
import statistics
import sys
from itertools import groupby
from pathlib import Path

import cv2

PAIRS_MANIFEST = Path("viewer/data/pairs.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("alignment_json", type=Path, help="Path to an align.py JSON output")
    parser.add_argument("divergence_json", type=Path, help="Path to a compute_diff.py JSON output")
    parser.add_argument(
        "--end-event-a",
        type=float,
        default=None,
        help="Timestamp (seconds, video_a's own clock) where video_a's attempt effectively "
        "ends (e.g. a fall) - steps at/after this are labeled 'ended' and excluded from "
        "summary stats. Manually supplied; not auto-detected (default: none)",
    )
    parser.add_argument(
        "--end-event-b",
        type=float,
        default=None,
        help="Same as --end-event-a, but for video_b's own clock (default: none)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write data.json and screenshots into "
        "(default: viewer/data/<label_a>_vs_<label_b>/)",
    )
    return parser.parse_args()


def load(path: Path):
    with open(path) as f:
        return json.load(f)


def derive_overlay_path(video_path: str) -> Path:
    stem = Path(video_path).stem
    return Path("output") / stem / f"{stem}_overlay.mp4"


def label_for(video_path: str) -> str:
    return Path(video_path).stem


def build_regions(steps: list):
    """Collapses contiguous same-region steps into labeled ranges for the
    graph to render as background bands."""
    regions = []
    for region, group in groupby(steps, key=lambda s: s["region"]):
        group = list(group)
        if region == "normal":
            continue
        start, end = group[0], group[-1]
        if region == "stall":
            label = f"DTW stall ({start['stall_side']} stuck)"
        else:
            label = "attempt ended"
        regions.append(
            {
                "type": region,
                "start_step": start["step"],
                "end_step": end["step"],
                "start_timestamp_a": start["timestamp_a"],
                "end_timestamp_a": end["timestamp_a"],
                "label": label,
            }
        )
    return regions


FRAME_HEIGHT = 720
FRAMES_ROOT = Path("viewer/frames")


def frame_path(frames_dir: Path, index: int) -> Path:
    return frames_dir / f"{index:06d}.jpg"


def extract_all_frames(video_path: Path, label: str, height: int = FRAME_HEIGHT):
    """Extracts every frame of video_path as a downscaled JPEG into
    viewer/frames/<label>/000000.jpg, 000001.jpg, ... Sequential cv2.read()
    only - no per-frame seeking, which is slow and was the whole reason the
    <video>-based approach this replaces was laggy. Skips extraction if the
    expected frame count is already present (per-attempt, not per-pair, so
    re-running on a different pair sharing this attempt is a no-op here).
    Returns (frame_count, width, height)."""
    frames_dir = FRAMES_ROOT / label
    frames_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(
            f"overlay video not found or unreadable: {video_path} - "
            f"did visualize_pose.py run for this attempt?"
        )
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    expected_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    new_width = max(1, round(width * height / orig_height))

    if expected_count > 0 and frame_path(frames_dir, expected_count - 1).exists():
        cap.release()
        print(f"  {label}: {expected_count} frames already extracted, skipping", file=sys.stderr)
        return expected_count, new_width, height

    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        resized = cv2.resize(frame, (new_width, height))
        cv2.imwrite(str(frame_path(frames_dir, n)), resized, [cv2.IMWRITE_JPEG_QUALITY, 85])
        n += 1
    cap.release()
    print(f"  {label}: extracted {n} frames to {frames_dir}", file=sys.stderr)
    return n, new_width, height


def update_manifest(pair_name: str, data_path: str):
    PAIRS_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    pairs = load(PAIRS_MANIFEST) if PAIRS_MANIFEST.exists() else []
    pairs = [p for p in pairs if p["name"] != pair_name]
    pairs.append({"name": pair_name, "data_path": data_path})
    pairs.sort(key=lambda p: p["name"])
    with open(PAIRS_MANIFEST, "w") as f:
        json.dump(pairs, f, indent=2)


def main() -> int:
    args = parse_args()

    for p in (args.alignment_json, args.divergence_json):
        if not p.exists():
            print(f"Error: file not found: {p}", file=sys.stderr)
            return 1

    alignment = load(args.alignment_json)
    divergence = load(args.divergence_json)

    label_a, label_b = label_for(alignment["video_a"]), label_for(alignment["video_b"])
    overlay_a = derive_overlay_path(alignment["video_a"])
    overlay_b = derive_overlay_path(alignment["video_b"])

    # Which side each stall step belongs to, and its divergence/joint values,
    # keyed by the original path step index (compute_diff.py preserves this
    # even though it dropped some steps).
    stall_side_by_step = {}
    for stall in divergence.get("excised_stalls", []):
        for i in range(stall["start_step"], stall["end_step"] + 1):
            stall_side_by_step[i] = stall["side"]
    divergence_by_step = {s["step"]: s for s in divergence["steps"]}

    steps_out = []
    for step, entry in enumerate(alignment["path"]):
        is_ended = (args.end_event_a is not None and entry["timestamp_a"] >= args.end_event_a) or (
            args.end_event_b is not None and entry["timestamp_b"] >= args.end_event_b
        )

        div_entry = divergence_by_step.get(step)
        total_divergence = div_entry["total_divergence"] if div_entry else None
        joints = div_entry["joints"] if div_entry else None

        if is_ended:
            region = "ended"
        elif step in stall_side_by_step:
            region = "stall"
        else:
            region = "normal"

        steps_out.append(
            {
                "step": step,
                "frame_a": entry["frame_a"],
                "timestamp_a": entry["timestamp_a"],
                "frame_b": entry["frame_b"],
                "timestamp_b": entry["timestamp_b"],
                "divergence": total_divergence,
                "joints": joints,
                "region": region,
                "stall_side": stall_side_by_step.get(step),
            }
        )

    regions = build_regions(steps_out)

    normal_steps = [s for s in steps_out if s["region"] == "normal" and s["divergence"] is not None]
    if not normal_steps:
        print("Error: no 'normal' steps with valid divergence - cannot compute summary stats", file=sys.stderr)
        return 1

    avg_divergence = statistics.mean(s["divergence"] for s in normal_steps)
    peak_step = max(normal_steps, key=lambda s: s["divergence"])

    joint_totals = {joint: [] for joint in divergence["joints_used"]}
    for s in normal_steps:
        for joint, value in s["joints"].items():
            if value is not None:
                joint_totals[joint].append(value)
    joint_breakdown = sorted(
        (
            {"joint": joint, "avg_divergence": statistics.mean(values), "n_valid_steps": len(values)}
            for joint, values in joint_totals.items()
            if values
        ),
        key=lambda j: j["avg_divergence"],
        reverse=True,
    )

    pair_name = f"{label_a}_vs_{label_b}"
    output_dir = args.output_dir or Path("viewer/data") / pair_name
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Extracting frames for canvas playback...", file=sys.stderr)
    n_a, width_a, height_a = extract_all_frames(overlay_a, label_a)
    n_b, width_b, height_b = extract_all_frames(overlay_b, label_b)
    if (width_a, height_a) != (width_b, height_b):
        print(
            f"Warning: {label_a} frames are {width_a}x{height_a} but {label_b} are "
            f"{width_b}x{height_b} - canvases will be sized independently",
            file=sys.stderr,
        )

    frames_dir_a = "/" + str(FRAMES_ROOT / label_a).replace("\\", "/") + "/"
    frames_dir_b = "/" + str(FRAMES_ROOT / label_b).replace("\\", "/") + "/"

    screenshot_a_path = output_dir / "peak_a.jpg"
    screenshot_b_path = output_dir / "peak_b.jpg"
    shutil.copyfile(frame_path(FRAMES_ROOT / label_a, peak_step["frame_a"]), screenshot_a_path)
    shutil.copyfile(frame_path(FRAMES_ROOT / label_b, peak_step["frame_b"]), screenshot_b_path)

    data = {
        "pair_name": pair_name,
        "label_a": label_a,
        "label_b": label_b,
        "frames_dir_a": frames_dir_a,
        "frames_dir_b": frames_dir_b,
        "frame_count_a": n_a,
        "frame_count_b": n_b,
        "frame_width_a": width_a,
        "frame_height_a": height_a,
        "frame_width_b": width_b,
        "frame_height_b": height_b,
        "joints_used": divergence["joints_used"],
        "joints_excluded": alignment["joints_excluded"],
        "steps": steps_out,
        "regions": regions,
        "summary": {
            "avg_divergence": avg_divergence,
            "peak_divergence": {
                "value": peak_step["divergence"],
                "step": peak_step["step"],
                "timestamp_a": peak_step["timestamp_a"],
                "timestamp_b": peak_step["timestamp_b"],
                "frame_a": peak_step["frame_a"],
                "frame_b": peak_step["frame_b"],
            },
            "joints_compared_count": len(divergence["joints_used"]),
            "joint_breakdown": joint_breakdown,
        },
        "screenshots": {"a": "peak_a.jpg", "b": "peak_b.jpg"},
    }

    data_path = output_dir / "data.json"
    with open(data_path, "w") as f:
        json.dump(data, f)

    update_manifest(pair_name, "/" + str(data_path).replace("\\", "/"))

    print(f"Regions: {len(regions)} ({sum(1 for r in regions if r['type'] == 'stall')} stall, "
          f"{sum(1 for r in regions if r['type'] == 'ended')} ended)", file=sys.stderr)
    print(f"Avg divergence (normal steps): {avg_divergence:.2f}", file=sys.stderr)
    print(
        f"Peak divergence: {peak_step['divergence']:.2f} at step {peak_step['step']} "
        f"(t_a={peak_step['timestamp_a']:.2f}s, t_b={peak_step['timestamp_b']:.2f}s)",
        file=sys.stderr,
    )
    print(f"Wrote {data_path}", file=sys.stderr)
    print(f"Wrote {screenshot_a_path}", file=sys.stderr)
    print(f"Wrote {screenshot_b_path}", file=sys.stderr)
    print(f"Updated {PAIRS_MANIFEST}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
