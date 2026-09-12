"""Place two videos side by side with each side's own burned-in elapsed
timestamp, for direct visual comparison. Both videos play at their own
normal, unmodified speed/length - nothing is trimmed or synced. Once the
shorter video runs out of frames, it freezes on its last frame (labeled
"ended") while the longer one keeps playing.

Usage:
    python sidebyside.py output/attempt_f/attempt_f_overlay.mp4 output/attempt_g/attempt_g_overlay.mp4
"""

import argparse
import sys
from pathlib import Path

import cv2

TEXT_COLOR = (255, 255, 255)  # white (BGR)
BOX_COLOR = (0, 0, 0)  # black backdrop behind text, for legibility


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_a", type=Path, help="First video (left side)")
    parser.add_argument("video_b", type=Path, help="Second video (right side)")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path for the side-by-side video "
        "(default: output/<a_label>_vs_<b_label>_sidebyside.mp4)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=1080,
        help="Common height (px) each side is scaled to before placing side by side (default: 1080)",
    )
    return parser.parse_args()


def label_for(video_path: Path) -> str:
    name = video_path.stem
    if name.endswith("_overlay"):
        name = name[: -len("_overlay")]
    return name


def open_video(path: Path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    return cap, fps, n_frames


def resize_to_height(frame, height: int):
    h, w = frame.shape[:2]
    new_w = max(1, round(w * height / h))
    return cv2.resize(frame, (new_w, height))


def draw_label(frame, text: str, scale: float):
    font = cv2.FONT_HERSHEY_SIMPLEX
    thickness = max(2, round(scale * 2))
    (text_w, text_h), baseline = cv2.getTextSize(text, font, scale, thickness)
    pad = round(scale * 12)
    x, y = pad, pad + text_h
    cv2.rectangle(
        frame,
        (x - pad // 2, y - text_h - pad // 2),
        (x + text_w + pad // 2, y + baseline + pad // 2),
        BOX_COLOR,
        -1,
    )
    cv2.putText(frame, text, (x, y), font, scale, TEXT_COLOR, thickness, cv2.LINE_AA)


def main() -> int:
    args = parse_args()

    for p in (args.video_a, args.video_b):
        if not p.exists():
            print(f"Error: video file not found: {p}", file=sys.stderr)
            return 1

    label_a, label_b = label_for(args.video_a), label_for(args.video_b)

    cap_a, fps_a, n_a = open_video(args.video_a)
    cap_b, fps_b, n_b = open_video(args.video_b)

    total_frames = max(n_a, n_b)
    text_scale = args.height / 1080 * 1.8

    output_path = args.output or Path("output") / f"{label_a}_vs_{label_b}_sidebyside.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    writer = None
    last_frame_a = last_frame_b = None

    for i in range(total_frames):
        if i < n_a:
            ok, frame_a = cap_a.read()
            if ok:
                last_frame_a = frame_a
            timestamp_a = i / fps_a
            ended_a = False
        else:
            timestamp_a = (n_a - 1) / fps_a
            ended_a = True
        frame_a = last_frame_a.copy()

        if i < n_b:
            ok, frame_b = cap_b.read()
            if ok:
                last_frame_b = frame_b
            timestamp_b = i / fps_b
            ended_b = False
        else:
            timestamp_b = (n_b - 1) / fps_b
            ended_b = True
        frame_b = last_frame_b.copy()

        frame_a = resize_to_height(frame_a, args.height)
        frame_b = resize_to_height(frame_b, args.height)

        label_text_a = f"{label_a}: {timestamp_a:.2f}s" + (" (ended)" if ended_a else "")
        label_text_b = f"{label_b}: {timestamp_b:.2f}s" + (" (ended)" if ended_b else "")
        draw_label(frame_a, label_text_a, text_scale)
        draw_label(frame_b, label_text_b, text_scale)

        combined = cv2.hconcat([frame_a, frame_b])

        if writer is None:
            out_fps = fps_a  # both sources are ~59.4fps here; each side still uses its own fps for its own timestamp above
            writer = cv2.VideoWriter(
                str(output_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                out_fps,
                (combined.shape[1], combined.shape[0]),
            )

        writer.write(combined)

        if (i + 1) % 30 == 0:
            print(f"Rendered {i + 1}/{total_frames} frames...", file=sys.stderr)

    cap_a.release()
    cap_b.release()
    if writer is not None:
        writer.release()

    print(f"Done: {total_frames} frames rendered.", file=sys.stderr)
    print(f"Wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
