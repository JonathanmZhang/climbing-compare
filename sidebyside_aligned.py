"""Place two overlay videos side by side, synced according to an align.py
DTW correspondence path rather than real time. Each path step shows
frame_a next to frame_b, with each side's own real timestamp burned on -
so stalls in the path (the same frame_a or frame_b repeated across
consecutive steps) show up as that side visibly pausing, which is the
point: it makes the alignment's behavior directly visible, good or bad.

Usage:
    python sidebyside_aligned.py output/attempt_f_vs_attempt_g_alignment.json \\
        output/attempt_f/attempt_f_overlay.mp4 output/attempt_g/attempt_g_overlay.mp4
"""

import argparse
import json
import sys
from pathlib import Path

import cv2

from sidebyside import draw_label, label_for, open_video, resize_to_height


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("alignment_json", type=Path, help="Path to an align.py JSON output")
    parser.add_argument("video_a", type=Path, help="Overlay video matching the alignment's video_a (left side)")
    parser.add_argument("video_b", type=Path, help="Overlay video matching the alignment's video_b (right side)")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path for the synced side-by-side video "
        "(default: output/<a_label>_vs_<b_label>_synced.mp4)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=1080,
        help="Common height (px) each side is scaled to before placing side by side (default: 1080)",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Playback fps for the output container (default: video_a's own fps)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    for p in (args.alignment_json, args.video_a, args.video_b):
        if not p.exists():
            print(f"Error: file not found: {p}", file=sys.stderr)
            return 1

    with open(args.alignment_json) as f:
        alignment = json.load(f)
    path = alignment["path"]

    label_a, label_b = label_for(args.video_a), label_for(args.video_b)

    cap_a, fps_a, n_a = open_video(args.video_a)
    cap_b, fps_b, n_b = open_video(args.video_b)

    out_fps = args.fps or fps_a
    text_scale = args.height / 1080 * 1.8

    output_path = args.output or Path("output") / f"{label_a}_vs_{label_b}_synced.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    writer = None
    current_frame_a = current_frame_b = None
    prev_frame_a_idx = prev_frame_b_idx = None

    for step, entry in enumerate(path):
        if entry["frame_a"] != prev_frame_a_idx:
            ok, current_frame_a = cap_a.read()
            if not ok:
                print(f"Error: ran out of frames reading {args.video_a} at path step {step}", file=sys.stderr)
                return 1
            prev_frame_a_idx = entry["frame_a"]

        if entry["frame_b"] != prev_frame_b_idx:
            ok, current_frame_b = cap_b.read()
            if not ok:
                print(f"Error: ran out of frames reading {args.video_b} at path step {step}", file=sys.stderr)
                return 1
            prev_frame_b_idx = entry["frame_b"]

        frame_a = resize_to_height(current_frame_a, args.height)
        frame_b = resize_to_height(current_frame_b, args.height)

        draw_label(frame_a, f"{label_a}: {entry['timestamp_a']:.2f}s", text_scale)
        draw_label(frame_b, f"{label_b}: {entry['timestamp_b']:.2f}s", text_scale)

        combined = cv2.hconcat([frame_a, frame_b])

        if writer is None:
            writer = cv2.VideoWriter(
                str(output_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                out_fps,
                (combined.shape[1], combined.shape[0]),
            )

        writer.write(combined)

        if (step + 1) % 100 == 0:
            print(f"Rendered {step + 1}/{len(path)} path steps...", file=sys.stderr)

    cap_a.release()
    cap_b.release()
    if writer is not None:
        writer.release()

    print(f"Done: {len(path)} path steps rendered.", file=sys.stderr)
    print(f"Wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
