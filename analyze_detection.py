"""Report on pose-detection dropout in an extract_pose.py JSON output.

Distinguishes leading/trailing frames with no detected pose (likely just
setup time before/after the climber is in frame) from no-detection frames
that fall *within* the range where a pose was actually being tracked
(a real tracking problem worth investigating).

Usage:
    python analyze_detection.py output/attempt_a.json
"""

import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", type=Path, help="Path to an extract_pose.py JSON output")
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="How many of the longest no-detection runs to list (default: 10)",
    )
    return parser.parse_args()


def fmt_time(frame_index: int, fps: float) -> str:
    return f"{frame_index / fps:.2f}s"


def main() -> int:
    args = parse_args()

    if not args.json.exists():
        print(f"Error: JSON file not found: {args.json}", file=sys.stderr)
        return 1

    with open(args.json) as f:
        data = json.load(f)

    fps = data["fps"]
    frames = data["frames"]
    total_frames = len(frames)

    detected_indices = [f["frame_index"] for f in frames if f["landmarks_2d"] is not None]

    if not detected_indices:
        print("No pose was detected in ANY frame of this video.")
        return 0

    first_detected = min(detected_indices)
    last_detected = max(detected_indices)
    active_span = last_detected - first_detected + 1

    leading_empty = first_detected
    trailing_empty = total_frames - 1 - last_detected

    # Restrict to the active range and find runs of consecutive no-detection frames.
    active_frames = frames[first_detected : last_detected + 1]
    runs = []  # list of (start_frame_index, end_frame_index) inclusive
    run_start = None
    for f in active_frames:
        if f["landmarks_2d"] is None:
            if run_start is None:
                run_start = f["frame_index"]
        else:
            if run_start is not None:
                runs.append((run_start, f["frame_index"] - 1))
                run_start = None
    if run_start is not None:
        runs.append((run_start, active_frames[-1]["frame_index"]))

    no_detection_in_active = sum(end - start + 1 for start, end in runs)

    print("=== Pose detection summary ===")
    print(f"Video: {data.get('video', args.json.stem)}")
    print(f"FPS: {fps:.3f}")
    print(f"Total frames: {total_frames}")
    print(f"Frames with a detected pose: {len(detected_indices)} ({len(detected_indices) / total_frames:.1%})")
    print(f"Frames with NO detected pose: {total_frames - len(detected_indices)} ({(total_frames - len(detected_indices)) / total_frames:.1%})")
    print()

    print("=== 1. Detection range ===")
    print(f"First detected frame: {first_detected} ({fmt_time(first_detected, fps)})")
    print(f"Last detected frame:  {last_detected} ({fmt_time(last_detected, fps)})")
    print(f"Leading no-detection frames (before first detection): {leading_empty} ({fmt_time(leading_empty, fps) if leading_empty else '0.00s'})")
    print(f"Trailing no-detection frames (after last detection):  {trailing_empty} ({fmt_time(trailing_empty, fps) if trailing_empty else '0.00s'})")
    print()

    print("=== 2. No-detection frames within the active range ===")
    print(f"Active range size: {active_span} frames ({fmt_time(active_span, fps)})")
    print(f"No-detection frames inside active range: {no_detection_in_active} ({no_detection_in_active / active_span:.1%} of active range)")
    print(f"Number of separate no-detection runs (clusters) inside active range: {len(runs)}")
    if runs:
        run_lengths = [end - start + 1 for start, end in runs]
        avg_len = sum(run_lengths) / len(run_lengths)
        print(f"Average run length: {avg_len:.1f} frames ({avg_len / fps:.2f}s)")
        print(f"Median run length: {sorted(run_lengths)[len(run_lengths) // 2]} frames")
        single_frame_runs = sum(1 for l in run_lengths if l == 1)
        print(f"Single-frame dropouts (length 1): {single_frame_runs} of {len(runs)} runs")
        if len(runs) > 1:
            print(
                "-> Many small/scattered runs suggests intermittent tracking noise; "
                "a few very long runs suggest a specific problem section."
            )
    print()

    print(f"=== 3. Longest no-detection runs within active range (top {args.top_n}) ===")
    if not runs:
        print("None — every frame in the active range had a detected pose.")
    else:
        sorted_runs = sorted(runs, key=lambda r: r[1] - r[0], reverse=True)
        for start, end in sorted_runs[: args.top_n]:
            length = end - start + 1
            print(
                f"  frames {start}-{end} "
                f"({fmt_time(start, fps)}-{fmt_time(end, fps)}), "
                f"{length} frames ({length / fps:.2f}s)"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
