"""Compute joint angles over time from an extract_pose.py JSON output.

Converts raw 3D world-landmark positions into joint angles (a property of
the body's own configuration, comparable across videos shot from different
camera angles). For each joint, computes a raw angle per frame, fills
low-visibility/no-detection gaps by interpolating from nearby good frames
(but only across gaps up to --max-gap-seconds long; longer gaps - including
at the start/end of the clip - are left null rather than held flat), then
smooths the result with a Savitzky-Golay filter (also skipping null gaps).

Usage:
    python compute_angles.py output/attempt_b.json
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.signal import savgol_filter

# Each joint's angle is the angle between two vectors pointing AWAY from the
# joint, toward the two named landmarks. 180 degrees = the joint is straight.
JOINT_DEFINITIONS = {
    "left_elbow": ("LEFT_ELBOW", "LEFT_SHOULDER", "LEFT_WRIST"),
    "right_elbow": ("RIGHT_ELBOW", "RIGHT_SHOULDER", "RIGHT_WRIST"),
    "left_shoulder": ("LEFT_SHOULDER", "LEFT_ELBOW", "LEFT_HIP"),
    "right_shoulder": ("RIGHT_SHOULDER", "RIGHT_ELBOW", "RIGHT_HIP"),
    "left_hip": ("LEFT_HIP", "LEFT_KNEE", "LEFT_SHOULDER"),
    "right_hip": ("RIGHT_HIP", "RIGHT_KNEE", "RIGHT_SHOULDER"),
    "left_knee": ("LEFT_KNEE", "LEFT_HIP", "LEFT_ANKLE"),
    "right_knee": ("RIGHT_KNEE", "RIGHT_HIP", "RIGHT_ANKLE"),
}
# torso_lean is handled separately: it needs a midpoint of two landmarks on
# each end, rather than a single shared joint vertex.
TORSO_LEAN_LANDMARKS = ("LEFT_SHOULDER", "RIGHT_SHOULDER", "LEFT_HIP", "RIGHT_HIP")
WORLD_UP = np.array([0.0, -1.0, 0.0])  # MediaPipe world landmarks: y increases downward

JOINT_NAMES = list(JOINT_DEFINITIONS.keys()) + ["torso_lean"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", type=Path, help="Path to an extract_pose.py JSON output")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path for the output JSON (default: <alongside input>/<stem>_angles.json)",
    )
    parser.add_argument(
        "--max-gap-seconds",
        type=float,
        default=1.0,
        help="Interpolate a joint across a gap only if it's at most this long; "
        "longer gaps (including leading/trailing) are left null instead of "
        "held flat (default: 1.0)",
    )
    parser.add_argument(
        "--savgol-window",
        type=int,
        default=11,
        help="Savitzky-Golay filter window length in frames, must be odd (default: 11)",
    )
    parser.add_argument(
        "--savgol-polyorder",
        type=int,
        default=2,
        help="Savitzky-Golay filter polynomial order (default: 2)",
    )
    return parser.parse_args()


def landmark_vec(landmarks, index):
    lm = landmarks[index]
    return np.array([lm["x"], lm["y"], lm["z"]])


def angle_between(v1: np.ndarray, v2: np.ndarray):
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 == 0 or n2 == 0:
        return None
    cos_angle = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
    return float(np.degrees(np.arccos(cos_angle)))


def landmarks_ok(landmarks, indices) -> bool:
    return all(not landmarks[i]["low_visibility"] for i in indices)


def compute_raw_angles(frames, name_to_index):
    """Returns {joint_name: [angle-or-None per frame]}."""
    raw = {name: [] for name in JOINT_NAMES}

    joint_indices = {
        name: tuple(name_to_index[n] for n in landmark_names)
        for name, landmark_names in JOINT_DEFINITIONS.items()
    }
    torso_indices = tuple(name_to_index[n] for n in TORSO_LEAN_LANDMARKS)

    for frame in frames:
        landmarks = frame["landmarks_3d_world"]

        if landmarks is None:
            for name in JOINT_NAMES:
                raw[name].append(None)
            continue

        for name, (joint_idx, a_idx, b_idx) in joint_indices.items():
            if landmarks_ok(landmarks, (joint_idx, a_idx, b_idx)):
                joint = landmark_vec(landmarks, joint_idx)
                v1 = landmark_vec(landmarks, a_idx) - joint
                v2 = landmark_vec(landmarks, b_idx) - joint
                raw[name].append(angle_between(v1, v2))
            else:
                raw[name].append(None)

        ls_i, rs_i, lh_i, rh_i = torso_indices
        if landmarks_ok(landmarks, torso_indices):
            shoulder_mid = (landmark_vec(landmarks, ls_i) + landmark_vec(landmarks, rs_i)) / 2
            hip_mid = (landmark_vec(landmarks, lh_i) + landmark_vec(landmarks, rh_i)) / 2
            raw["torso_lean"].append(angle_between(shoulder_mid - hip_mid, WORLD_UP))
        else:
            raw["torso_lean"].append(None)

    return raw


def interpolate(values, timestamps, max_gap_seconds: float):
    """Fill None gaps by linear interpolation, but only where the gap's
    duration is <= max_gap_seconds (checked against the gap's own span, i.e.
    the time between its first and last missing frame). Longer gaps -
    including leading/trailing ones with only one bound - are left as None
    rather than held flat. Returns (values, n_interpolated, n_left_null)."""
    n = len(values)
    result = [None] * n
    n_interpolated = 0
    n_left_null = 0

    i = 0
    while i < n:
        if values[i] is not None:
            result[i] = float(values[i])
            i += 1
            continue

        gap_start = i
        j = i
        while j < n and values[j] is None:
            j += 1
        gap_end = j - 1  # inclusive

        gap_duration = timestamps[gap_end] - timestamps[gap_start]
        has_left = gap_start > 0
        has_right = gap_end < n - 1

        if gap_duration <= max_gap_seconds and (has_left or has_right):
            if has_left and has_right:
                left_t, left_v = timestamps[gap_start - 1], values[gap_start - 1]
                right_t, right_v = timestamps[gap_end + 1], values[gap_end + 1]
                for k in range(gap_start, gap_end + 1):
                    result[k] = float(np.interp(timestamps[k], [left_t, right_t], [left_v, right_v]))
            elif has_right:
                fill_v = values[gap_end + 1]
                for k in range(gap_start, gap_end + 1):
                    result[k] = float(fill_v)
            else:  # has_left only
                fill_v = values[gap_start - 1]
                for k in range(gap_start, gap_end + 1):
                    result[k] = float(fill_v)
            n_interpolated += gap_end - gap_start + 1
        else:
            n_left_null += gap_end - gap_start + 1

        i = j

    return result, n_interpolated, n_left_null


def _savgol_segment(segment, window_length: int, polyorder: int):
    n = len(segment)
    wl = window_length
    if wl > n:
        wl = n if n % 2 == 1 else n - 1
    if wl % 2 == 0:
        wl -= 1
    if wl <= polyorder or wl < 1:
        return list(segment), False
    return [float(v) for v in savgol_filter(segment, wl, polyorder)], wl != window_length


def smooth(values, window_length: int, polyorder: int, label: str):
    """Applies Savitzky-Golay smoothing independently to each contiguous
    non-null run in `values`, leaving None where values is None (never
    smooths across a null gap)."""
    n = len(values)
    result = [None] * n
    any_shrunk = False

    i = 0
    while i < n:
        if values[i] is None:
            i += 1
            continue
        j = i
        while j < n and values[j] is not None:
            j += 1
        smoothed_segment, shrunk = _savgol_segment(values[i:j], window_length, polyorder)
        result[i:j] = smoothed_segment
        any_shrunk = any_shrunk or shrunk
        i = j

    if any_shrunk:
        print(f"Warning: savgol window shrunk for '{label}' on a short segment", file=sys.stderr)

    return result


def main() -> int:
    args = parse_args()

    if not args.json.exists():
        print(f"Error: JSON file not found: {args.json}", file=sys.stderr)
        return 1

    with open(args.json) as f:
        data = json.load(f)

    name_to_index = {name: i for i, name in enumerate(data["landmark_names"])}
    frames = data["frames"]
    timestamps = np.array([f["timestamp"] for f in frames])

    raw = compute_raw_angles(frames, name_to_index)

    output_frames = [
        {"frame_index": f["frame_index"], "timestamp": f["timestamp"], "joints": {}}
        for f in frames
    ]

    for name in JOINT_NAMES:
        interpolated, n_interpolated, n_left_null = interpolate(
            raw[name], timestamps, args.max_gap_seconds
        )
        smoothed = smooth(interpolated, args.savgol_window, args.savgol_polyorder, name)

        n_missing = sum(1 for v in raw[name] if v is None)
        print(
            f"{name}: {n_missing}/{len(frames)} raw frames missing "
            f"({n_interpolated} interpolated, {n_left_null} left null: gap > {args.max_gap_seconds}s)",
            file=sys.stderr,
        )

        for i, frame_out in enumerate(output_frames):
            frame_out["joints"][name] = {
                "raw": raw[name][i],
                "interpolated": interpolated[i],
                "smoothed": smoothed[i],
            }

    output_path = args.output or args.json.parent / (args.json.stem + "_angles.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "video": data.get("video"),
        "fps": data["fps"],
        "max_gap_seconds": args.max_gap_seconds,
        "joint_names": JOINT_NAMES,
        "frames": output_frames,
    }

    with open(output_path, "w") as f:
        json.dump(output, f)

    print(f"Wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
