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
        "trim all further steps starting from where that stall began. Targets "
        "the actual failure mode directly rather than proximity to either "
        "video's end (default: 20)",
    )
    return parser.parse_args()


def find_stall_cutoff(path: list, max_stall_length: int):
    """Returns (cutoff_step, stall_info) for the first stall (a run of
    consecutive steps where frame_a - or separately frame_b - stays the same)
    that exceeds max_stall_length steps, or (None, None) if there is none.
    cutoff_step is the step where that stall began - everything from there
    onward should be dropped."""
    earliest = None
    for side, key_fn in (("frame_a", lambda p: p["frame_a"]), ("frame_b", lambda p: p["frame_b"])):
        pos = 0
        for key, group in groupby(path, key=key_fn):
            length = sum(1 for _ in group)
            if length > max_stall_length and (earliest is None or pos < earliest[0]):
                earliest = (pos, {"side": side, "value": key, "length": length})
            pos += length
    return earliest if earliest is not None else (None, None)


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
    cutoff_step, stall_info = find_stall_cutoff(full_path, args.max_stall_length)
    path_to_use = full_path[:cutoff_step] if cutoff_step is not None else full_path
    n_trimmed = len(full_path) - len(path_to_use)

    steps_out = []
    n_zero_valid = 0

    for step, entry in enumerate(path_to_use):
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

    if n_trimmed:
        last_kept = (
            f"t_a={steps_out[-1]['timestamp_a']:.2f}s, t_b={steps_out[-1]['timestamp_b']:.2f}s"
            if steps_out
            else "none kept"
        )
        print(
            f"Trimmed {n_trimmed} steps starting at step {cutoff_step}: {stall_info['side']}="
            f"{stall_info['value']} stayed fixed for {stall_info['length']} consecutive steps "
            f"(> --max-stall-length {args.max_stall_length}) -- last kept step: {last_kept}",
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
        "trimmed_at_stall": stall_info,
        "steps": steps_out,
    }

    with open(output_path, "w") as f:
        json.dump(output, f)

    print(f"Wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
