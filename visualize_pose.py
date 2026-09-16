"""Draw the 2D pose skeleton from an extract_pose.py JSON output back onto
its source video, so tracking quality can be checked visually.

Usage:
    python visualize_pose.py videos/attempt_a.mp4
    python visualize_pose.py videos/attempt_a.mp4 --json output/attempt_a/attempt_a.json --output output/attempt_a/attempt_a_overlay.mp4
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import mediapipe as mp

POSE_CONNECTIONS = mp.solutions.pose.POSE_CONNECTIONS

OK_COLOR = (0, 220, 0)  # green (BGR): visibility above threshold
LOW_VIS_COLOR = (0, 90, 255)  # orange (BGR): flagged low_visibility
LINE_COLOR = (200, 200, 200)  # light gray connector lines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="Path to the input video file")
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Path to the extract_pose.py JSON output (default: output/<video_stem>/<video_stem>.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path for the overlay video (default: output/<video_stem>/<video_stem>_overlay.mp4)",
    )
    return parser.parse_args()


def draw_skeleton(frame, landmarks_2d):
    if landmarks_2d is None:
        return

    points = [(int(round(lm["x"])), int(round(lm["y"]))) for lm in landmarks_2d]

    for start_idx, end_idx in POSE_CONNECTIONS:
        if start_idx >= len(points) or end_idx >= len(points):
            continue
        cv2.line(frame, points[start_idx], points[end_idx], LINE_COLOR, 3)

    for lm, point in zip(landmarks_2d, points):
        color = LOW_VIS_COLOR if lm["low_visibility"] else OK_COLOR
        cv2.circle(frame, point, 7, color, -1)


def main() -> int:
    args = parse_args()

    if not args.video.exists():
        print(f"Error: video file not found: {args.video}", file=sys.stderr)
        return 1

    json_path = args.json or Path("output") / args.video.stem / (args.video.stem + ".json")
    if not json_path.exists():
        print(f"Error: pose JSON not found: {json_path}", file=sys.stderr)
        print("Run extract_pose.py on this video first.", file=sys.stderr)
        return 1

    with open(json_path) as f:
        pose_data = json.load(f)

    frames_by_index = {f["frame_index"]: f for f in pose_data["frames"]}

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        print(f"Error: could not open video: {args.video}", file=sys.stderr)
        return 1

    fps = cap.get(cv2.CAP_PROP_FPS) or pose_data.get("fps") or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if total_frames and total_frames != len(pose_data["frames"]):
        print(
            f"Warning: video has {total_frames} frames but JSON has "
            f"{len(pose_data['frames'])} frames. They may not match up.",
            file=sys.stderr,
        )

    output_path = args.output or Path("output") / args.video.stem / (args.video.stem + "_overlay.mp4")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    frame_index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame_data = frames_by_index.get(frame_index)
        if frame_data is not None:
            draw_skeleton(frame, frame_data["landmarks_2d"])

        writer.write(frame)

        frame_index += 1
        if frame_index % 30 == 0:
            print(f"Rendered {frame_index} frames...", file=sys.stderr)

    cap.release()
    writer.release()

    print(f"Done: {frame_index} frames rendered.", file=sys.stderr)
    print(f"Wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
