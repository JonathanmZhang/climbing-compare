"""Run pose extraction + skeleton visualization on every video in videos/.

For each video, runs extract_pose.py then visualize_pose.py on it. Skips a
video entirely if its output JSON already exists, so re-running after
adding new footage doesn't redo extraction/visualization that's already
been done.

Usage:
    python batch_extract.py
"""

import argparse
import subprocess
import sys
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm"}

SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--videos-dir",
        type=Path,
        default=Path("videos"),
        help="Directory to scan for video files (default: videos/)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Root directory for per-video output subfolders, i.e. <output-dir>/<video_stem>/ "
        "(default: output/)",
    )
    return parser.parse_args()


def find_videos(videos_dir: Path) -> list[Path]:
    return sorted(
        p for p in videos_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )


def run(cmd: list) -> int:
    print(f"$ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd).returncode


def main() -> int:
    args = parse_args()

    if not args.videos_dir.exists():
        print(f"Error: videos directory not found: {args.videos_dir}", file=sys.stderr)
        return 1

    videos = find_videos(args.videos_dir)
    if not videos:
        print(f"No video files found in {args.videos_dir}", flush=True)
        return 0

    processed = skipped = failed = 0

    for video in videos:
        video_output_dir = args.output_dir / video.stem
        json_path = video_output_dir / (video.stem + ".json")

        if json_path.exists():
            print(f"[skip] {video.name}: {json_path} already exists", flush=True)
            skipped += 1
            continue

        print(f"[extract] {video.name}", flush=True)
        extract_cmd = [
            sys.executable,
            str(SCRIPT_DIR / "extract_pose.py"),
            str(video),
            "--output-dir",
            str(video_output_dir),
        ]
        if run(extract_cmd) != 0:
            print(f"[fail] extract_pose.py failed on {video.name}, skipping visualization", file=sys.stderr)
            failed += 1
            continue

        print(f"[visualize] {video.name}", flush=True)
        overlay_path = video_output_dir / (video.stem + "_overlay.mp4")
        visualize_cmd = [
            sys.executable,
            str(SCRIPT_DIR / "visualize_pose.py"),
            str(video),
            "--json",
            str(json_path),
            "--output",
            str(overlay_path),
        ]
        if run(visualize_cmd) != 0:
            print(f"[fail] visualize_pose.py failed on {video.name}", file=sys.stderr)
            failed += 1
            continue

        processed += 1

    print()
    print(f"Done: {processed} processed, {skipped} skipped, {failed} failed (of {len(videos)} videos found).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
