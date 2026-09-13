"""Compute per-step divergence between two attempts using an align.py
alignment path.

For each aligned step, computes the absolute difference in each joint's
smoothed angle between the two attempts' corresponding frames, then a total
divergence score (mean absolute difference across the joints valid at that
step). Reuses align.py's own joints_used list for this pair rather than
re-deriving joint reliability - a joint align.py already excluded as
unreliable for this pair doesn't reappear here. On top of that, a joint only
counts at a given step if it's non-null in BOTH frames (same masking
philosophy as align.py) - never invents data for a missing joint.

Usage:
    python compute_diff.py output/attempt_f_vs_attempt_g_alignment.json
"""

import argparse
import json
import sys
import statistics
from itertools import groupby
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("alignment_json", type=Path, help="Path to an align.py JSON output")
    parser.add_argument(
        "--angles-a",
        type=Path,
        default=None,
        help="Path to video_a's compute_angles.py output "
        "(default: derived from the alignment JSON's video_a, as output/<stem>/<stem>_angles.json)",
    )
    parser.add_argument(
        "--angles-b",
        type=Path,
        default=None,
        help="Path to video_b's compute_angles.py output (default: derived similarly for video_b)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path for the divergence JSON "
        "(default: output/<a_label>_vs_<b_label>_divergence.json)",
    )
    parser.add_argument(
        "--max-stall-length",
        type=int,
        default=20,
        help="Once a stall (frame_a or frame_b staying fixed across consecutive "
        "path steps - one side of the alignment stuck) exceeds this many steps, "
        "excise just those steps from the output and resume normal inclusion "
        "once the stall ends. Targets the actual failure mode directly rather "
        "than proximity to either video's end (default: 20)",
    )
    return parser.parse_args()


def find_stall_ranges(path: list, max_stall_length: int):
    """Returns a list of {"start_step", "end_step", "side", "value", "length"}
    for every run of consecutive steps where frame_a - or separately frame_b -
    stays fixed, longer than max_stall_length. Sorted by start_step; these
    runs never overlap (a DTW step always advances at least one of the two
    indices, so frame_a and frame_b can't both be mid-stall at once)."""
    stalls = []
    for side, key_fn in (("frame_a", lambda p: p["frame_a"]), ("frame_b", lambda p: p["frame_b"])):
        pos = 0
        for key, group in groupby(path, key=key_fn):
            length = sum(1 for _ in group)
            if length > max_stall_length:
                stalls.append(
                    {"start_step": pos, "end_step": pos + length - 1, "side": side, "value": key, "length": length}
                )
            pos += length
    stalls.sort(key=lambda s: s["start_step"])
    return stalls


def load(path: Path):
    with open(path) as f:
        return json.load(f)


def derive_angles_path(video_path: str) -> Path:
    stem = Path(video_path).stem
    return Path("output") / stem / f"{stem}_angles.json"


def label_for(path: Path) -> str:
    name = path.stem
    if name.endswith("_angles"):
        name = name[: -len("_angles")]
    return name


def main() -> int:
    args = parse_args()

    if not args.alignment_json.exists():
        print(f"Error: alignment JSON not found: {args.alignment_json}", file=sys.stderr)
        return 1

    alignment = load(args.alignment_json)

    angles_a_path = args.angles_a or derive_angles_path(alignment["video_a"])
    angles_b_path = args.angles_b or derive_angles_path(alignment["video_b"])

    for p in (angles_a_path, angles_b_path):
        if not p.exists():
            print(f"Error: angles JSON not found: {p}", file=sys.stderr)
            return 1

    data_a = load(angles_a_path)
    data_b = load(angles_b_path)

    joints_used = alignment["joints_used"]
    frames_a = data_a["frames"]
    frames_b = data_b["frames"]

    full_path = alignment["path"]
    stalls = find_stall_ranges(full_path, args.max_stall_length)
    excluded = [False] * len(full_path)
    for stall in stalls:
        for i in range(stall["start_step"], stall["end_step"] + 1):
            excluded[i] = True
    n_trimmed = sum(excluded)

    steps_out = []
    n_zero_valid = 0

    for step, entry in enumerate(full_path):
        if excluded[step]:
            continue

        joints_a = frames_a[entry["frame_a"]]["joints"]
        joints_b = frames_b[entry["frame_b"]]["joints"]

        joint_diffs = {}
        valid_diffs = []
        for joint in joints_used:
            v_a = joints_a[joint]["smoothed"]
            v_b = joints_b[joint]["smoothed"]
            if v_a is not None and v_b is not None:
                diff = abs(v_a - v_b)
                joint_diffs[joint] = diff
                valid_diffs.append(diff)
            else:
                joint_diffs[joint] = None

        if valid_diffs:
            total_divergence = sum(valid_diffs) / len(valid_diffs)
        else:
            total_divergence = None
            n_zero_valid += 1

        steps_out.append(
            {
                "step": step,
                "frame_a": entry["frame_a"],
                "timestamp_a": entry["timestamp_a"],
                "frame_b": entry["frame_b"],
                "timestamp_b": entry["timestamp_b"],
                "total_divergence": total_divergence,
                "joints": joint_diffs,
            }
        )

    if stalls:
        print(
            f"Excised {len(stalls)} stall(s), {n_trimmed} steps total "
            f"(> --max-stall-length {args.max_stall_length}):",
            file=sys.stderr,
        )
        for s in stalls:
            t_a_start = full_path[s["start_step"]]["timestamp_a"]
            t_a_end = full_path[s["end_step"]]["timestamp_a"]
            print(
                f"  steps {s['start_step']}-{s['end_step']} ({s['length']} steps, "
                f"t_a={t_a_start:.2f}s-{t_a_end:.2f}s): {s['side']}={s['value']} stayed fixed",
                file=sys.stderr,
            )

    if n_zero_valid:
        print(
            f"Warning: {n_zero_valid} of {len(steps_out)} steps had zero valid joints "
            f"(total_divergence left null)",
            file=sys.stderr,
        )

    valid_totals = [s["total_divergence"] for s in steps_out if s["total_divergence"] is not None]
    if valid_totals:
        print(
            f"Total divergence over {len(valid_totals)} valid steps: "
            f"min={min(valid_totals):.2f}  mean={statistics.mean(valid_totals):.2f}  "
            f"max={max(valid_totals):.2f}",
            file=sys.stderr,
        )

    label_a, label_b = label_for(angles_a_path), label_for(angles_b_path)
    output_path = args.output or Path("output") / f"{label_a}_vs_{label_b}_divergence.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "video_a": alignment["video_a"],
        "video_b": alignment["video_b"],
        "joints_used": joints_used,
        "max_stall_length": args.max_stall_length,
        "excised_stalls": stalls,
        "steps": steps_out,
    }

    with open(output_path, "w") as f:
        json.dump(output, f)

    print(f"Wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
