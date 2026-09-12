"""Temporally align two compute_angles.py JSON outputs of the same climb
using Dynamic Time Warping (DTW) on joint-angle feature vectors.

Since joint reliability varies per footage pair (not just per video), a
joint is excluded from this comparison entirely if it's null in more than
--null-threshold of either video's frames. Among the surviving joints, the
per-frame distance only counts joints valid in BOTH frames being compared
("masked distance") - it never invents data to fill a gap.

dtaidistance has no built-in support for masked/missing-data distances, so
this script computes the masked distance matrix itself and hands the
resulting accumulated-cost matrix to dtaidistance.dtw.best_path() to do the
actual DTW alignment (backtrace), matching its own internal convention for
dtw.warping_paths()'s "paths" matrix: shape (N+1, M+1), row 0 / column 0 are
inf except paths[0,0] = 0, and best_path() is a generic backtracker that
doesn't care how the interior values were produced.

Usage:
    python align.py output/attempt_f/attempt_f_angles.json output/attempt_g/attempt_g_angles.json
"""

""" ------------------------------------- PERSONAL NOTES HERE -------------------------------------
# --- my notes on how this works ---
Two separate filters happen here, not one:

1. Joint exclusion (choose_joints): a joint is thrown out entirely for
this video pair if it's unreliable in EITHER video (OR, not AND) -
even if one video tracked it perfectly, bad data on the other side
still makes it useless for comparison, since every comparison needs
both sides to have real data.

2. Masked distance (masked_distance_matrix): among the joints that
survive filter #1, when comparing any specific pair of frames, only
count a joint if it's valid in BOTH of those frames right now. This
catches occasional remaining gaps that filter #1 didn't already remove.
Neither filter invents data to cover a gap - same philosophy as the
Stage 2 interpolation fix (mark missing as missing, don't guess).

Separately: dtaidistance doesn't support masked/missing-data distances
natively, so this script builds its own custom distance matrix and its
own accumulated-cost matrix by hand, then only borrows dtaidistance's
best_path() function to do the final backtrace/path-finding step - that
function just reads a finished cost matrix, so it doesn't care that the
matrix was built manually instead of by dtaidistance itself.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from dtaidistance import dtw


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_a", type=Path, help="Path to the first compute_angles.py JSON output")
    parser.add_argument("json_b", type=Path, help="Path to the second compute_angles.py JSON output")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path for the alignment JSON "
        "(default: output/<a_name>_vs_<b_name>_alignment.json)",
    )
    parser.add_argument(
        "--null-threshold",
        type=float,
        default=0.5,
        help="Exclude a joint from this pair's comparison if it's null in more "
        "than this fraction of either video's frames (default: 0.5)",
    )
    parser.add_argument(
        "--min-valid-joints",
        type=int,
        default=4,
        help="A frame pair with fewer than this many mutually-valid joints (out "
        "of the joints used for this pair) gets a high penalty distance instead "
        "of a real average, since too few joints makes the average unreliable "
        "(default: 4)",
    )
    return parser.parse_args()


def load(path: Path):
    with open(path) as f:
        return json.load(f)


def null_fraction(data, joint: str) -> float:
    frames = data["frames"]

    # PERSONAL NOTE: this line sums up all instances of if the smoothed angle value from the iterated joint is null
    n_null = sum(1 for f in frames if f["joints"][joint]["smoothed"] is None)
    return n_null / len(frames)


def choose_joints(data_a, data_b, threshold: float):
    """Returns (used, excluded) where excluded is a list of
    {"joint", "null_pct_a", "null_pct_b"}."""
    used, excluded = [], []
    for joint in data_a["joint_names"]:
        # PERSONAL NOTE: calculating fraction of null joints to keep or remove them from the video
        pct_a = null_fraction(data_a, joint)
        pct_b = null_fraction(data_b, joint)
        if pct_a > threshold or pct_b > threshold:
            excluded.append({"joint": joint, "null_pct_a": pct_a, "null_pct_b": pct_b})
        else:
            used.append(joint)
    return used, excluded

# PERSONAL NOTE: formatting joint data to set null angles as NaN
def feature_matrix(data, joints: list):
    """Returns an (n_frames, len(joints)) array of smoothed angles, NaN where null."""
    frames = data["frames"]
    matrix = np.full((len(frames), len(joints)), np.nan)
    for i, frame in enumerate(frames):
        for k, joint in enumerate(joints):
            v = frame["joints"][joint]["smoothed"]
            if v is not None:
                matrix[i, k] = v
    return matrix


def masked_distance_matrix(feat_a: np.ndarray, feat_b: np.ndarray, min_valid_joints: int):
    """Mean absolute difference per frame pair, over joints valid in both.
    A frame pair with fewer than min_valid_joints mutually-valid joints has
    its distance estimate built from too little data to trust (the mean of
    a handful of values is noisy enough that it can look artificially cheap
    purely by chance), so it's replaced with a large penalty instead of the
    computed average. Returns (dist, n_low_count) where dist has shape
    (N, M) and n_low_count is the count of pairs that got the penalty."""
    n, m = feat_a.shape[0], feat_b.shape[0]
    sum_diff = np.zeros((n, m))
    valid_count = np.zeros((n, m), dtype=int)

    for k in range(feat_a.shape[1]):
        a_col = feat_a[:, k][:, None]  # (n, 1)
        b_col = feat_b[:, k][None, :]  # (1, m)
        valid = ~np.isnan(a_col) & ~np.isnan(b_col)  # (n, m)
        diff = np.abs(a_col - b_col)
        sum_diff += np.where(valid, diff, 0.0)
        valid_count += valid

    low_count_mask = valid_count < min_valid_joints  # includes the valid_count == 0 case
    n_low_count = int(low_count_mask.sum())

    with np.errstate(invalid="ignore", divide="ignore"):
        dist = sum_diff / valid_count

    if n_low_count > 0:
        trustworthy = ~low_count_mask
        max_trustworthy = float(np.max(dist[trustworthy])) if trustworthy.any() else 180.0
        penalty = max_trustworthy * 10
        dist = np.where(low_count_mask, penalty, dist)

    return dist, n_low_count


def dtw_accumulate(dist: np.ndarray) -> np.ndarray:
    """Standard DTW accumulated-cost matrix, in dtaidistance's own
    (N+1, M+1) boundary convention, seeded with our own pointwise distance
    instead of dtaidistance's built-in one."""
    n, m = dist.shape
    acc = np.full((n + 1, m + 1), np.inf)
    acc[0, 0] = 0.0

    for i in range(1, n + 1):
        acc_row, acc_prev_row = acc[i], acc[i - 1]
        dist_row = dist[i - 1]
        for j in range(1, m + 1):
            step = min(acc_prev_row[j], acc_row[j - 1], acc_prev_row[j - 1])
            acc_row[j] = dist_row[j - 1] + step

    return acc


def main() -> int:
    args = parse_args()

    for p in (args.json_a, args.json_b):
        if not p.exists():
            print(f"Error: JSON file not found: {p}", file=sys.stderr)
            return 1

    data_a = load(args.json_a)
    data_b = load(args.json_b)

    if data_a["joint_names"] != data_b["joint_names"]:
        print("Error: the two files have different joint_names sets", file=sys.stderr)
        return 1

    used, excluded = choose_joints(data_a, data_b, args.null_threshold)

    print("=== Joint selection for this pair ===", file=sys.stderr)
    for joint in data_a["joint_names"]:
        pct_a = null_fraction(data_a, joint)
        pct_b = null_fraction(data_b, joint)
        status = "EXCLUDED" if joint in {e["joint"] for e in excluded} else "used"
        print(f"  {joint:16s} null_a={pct_a:6.1%}  null_b={pct_b:6.1%}  -> {status}", file=sys.stderr)

    if not used:
        print("Error: every joint was excluded for this pair, nothing to align on", file=sys.stderr)
        return 1
    if len(used) < 3:
        print(f"Warning: only {len(used)} joint(s) survived exclusion; alignment quality may be low", file=sys.stderr)

    feat_a = feature_matrix(data_a, used)
    feat_b = feature_matrix(data_b, used)

    dist, n_low_count = masked_distance_matrix(feat_a, feat_b, args.min_valid_joints)
    if n_low_count:
        print(
            f"Warning: {n_low_count} of {dist.size} frame pairs had fewer than "
            f"{args.min_valid_joints} mutually-valid joints (out of {len(used)} used) "
            f"and got a penalty distance instead of a real average",
            file=sys.stderr,
        )

    acc = dtw_accumulate(dist)
    dtw_distance = float(acc[-1, -1])
    path = dtw.best_path(acc)

    frames_a = data_a["frames"]
    frames_b = data_b["frames"]
    path_out = [
        {
            "frame_a": i,
            "timestamp_a": frames_a[i]["timestamp"],
            "frame_b": j,
            "timestamp_b": frames_b[j]["timestamp"],
        }
        for i, j in path
    ]

    output_path = args.output or Path("output") / f"{args.json_a.parent.name}_vs_{args.json_b.parent.name}_alignment.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "video_a": data_a.get("video"),
        "video_b": data_b.get("video"),
        "joints_used": used,
        "joints_excluded": excluded,
        "dtw_distance": dtw_distance,
        "path": path_out,
    }

    with open(output_path, "w") as f:
        json.dump(output, f)

    print(file=sys.stderr)
    print(f"Joints used ({len(used)}): {', '.join(used)}", file=sys.stderr)
    print(f"Joints excluded ({len(excluded)}): {', '.join(e['joint'] for e in excluded) or 'none'}", file=sys.stderr)
    print(f"DTW distance: {dtw_distance:.3f}", file=sys.stderr)
    print(f"Path length: {len(path)} steps, spanning frame_a 0-{path[-1][0]} of {len(frames_a)-1}, "
            f"frame_b 0-{path[-1][1]} of {len(frames_b)-1}", file=sys.stderr)
    print(f"Wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
