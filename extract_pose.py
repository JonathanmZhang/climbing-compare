"""Run MediaPipe Pose over a video and dump per-frame landmarks to JSON.

Usage:
    python extract_pose.py videos/attempt_a.mp4
"""

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp

mp_pose = mp.solutions.pose

LANDMARK_NAMES = [lm.name for lm in mp_pose.PoseLandmark]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="Path to the input video file")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write the output JSON into (default: output/<video_stem>/)",
    )
    parser.add_argument(
        "--model-complexity",
        type=int,
        choices=[0, 1, 2],
        default=2,
        help="MediaPipe Pose model complexity, 0=fastest, 2=most accurate (default: 2)",
    )
    parser.add_argument(
        "--min-detection-confidence",
        type=float,
        default=0.5,
        help="Minimum confidence for the initial pose detection (default: 0.5)",
    )
    parser.add_argument(
        "--min-tracking-confidence",
        type=float,
        default=0.5,
        help="Minimum confidence for landmark tracking between frames (default: 0.5)",
    )
    parser.add_argument(
        "--visibility-threshold",
        type=float,
        default=0.5,
        help="Landmarks with visibility below this are flagged low_visibility (default: 0.5)",
    )
    return parser.parse_args()


def landmarks_2d_to_dict(pose_landmarks, width: int, height: int, threshold: float):
    if pose_landmarks is None:
        return None
    return [
        {
            "x": lm.x * width,
            "y": lm.y * height,
            "visibility": lm.visibility,
            "low_visibility": lm.visibility < threshold,
        }
        for lm in pose_landmarks.landmark
    ]


def landmarks_3d_to_dict(pose_world_landmarks, threshold: float):
    if pose_world_landmarks is None:
        return None
    return [
        {
            "x": lm.x,
            "y": lm.y,
            "z": lm.z,
            "visibility": lm.visibility,
            "low_visibility": lm.visibility < threshold,
        }
        for lm in pose_world_landmarks.landmark
    ]


def main() -> int:
    args = parse_args()

    if not args.video.exists():
        print(f"Error: video file not found: {args.video}", file=sys.stderr)
        return 1

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        print(f"Error: could not open video: {args.video}", file=sys.stderr)
        return 1

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if fps <= 0:
        print("Warning: video reports invalid FPS, defaulting to 30.0", file=sys.stderr)
        fps = 30.0

    output_dir = args.output_dir or Path("output") / args.video.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / (args.video.stem + ".json")

    frames = []
    frames_with_no_detection = 0
    frame_index = 0
    start_time = time.time()

    with mp_pose.Pose(
        static_image_mode=False,
        model_complexity=args.model_complexity,
        min_detection_confidence=args.min_detection_confidence,
        min_tracking_confidence=args.min_tracking_confidence,
    ) as pose:
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break

            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frame_rgb.flags.writeable = False
            results = pose.process(frame_rgb)

            landmarks_2d = landmarks_2d_to_dict(
                results.pose_landmarks, width, height, args.visibility_threshold
            )
            landmarks_3d = landmarks_3d_to_dict(
                results.pose_world_landmarks, args.visibility_threshold
            )

            if landmarks_2d is None:
                frames_with_no_detection += 1

            frames.append(
                {
                    "frame_index": frame_index,
                    "timestamp": frame_index / fps,
                    "landmarks_2d": landmarks_2d,
                    "landmarks_3d_world": landmarks_3d,
                }
            )

            frame_index += 1
            if frame_index % 30 == 0:
                print(f"Processed {frame_index} frames...", file=sys.stderr)

    cap.release()

    output = {
        "video": str(args.video).replace("\\", "/"),
        "fps": fps,
        "width": width,
        "height": height,
        "frame_count": frame_count,
        "landmark_names": LANDMARK_NAMES,
        "frames": frames,
    }

    with open(output_path, "w") as f:
        json.dump(output, f)

    elapsed = time.time() - start_time
    print(
        f"Done: {frame_index} frames processed in {elapsed:.1f}s "
        f"({frames_with_no_detection} frames with no pose detected).",
        file=sys.stderr,
    )
    print(f"Wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
