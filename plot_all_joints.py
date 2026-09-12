"""Run plot_angle.py for every joint in a compute_angles.py JSON output.

Usage:
    python plot_all_joints.py output/attempt_b/attempt_b_angles.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", type=Path, help="Path to a compute_angles.py JSON output")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write one PNG per joint into (default: <alongside input>/joints/)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.json.exists():
        print(f"Error: JSON file not found: {args.json}", file=sys.stderr)
        return 1

    with open(args.json) as f:
        data = json.load(f)

    output_dir = args.output_dir or args.json.parent / "joints"
    output_dir.mkdir(parents=True, exist_ok=True)

    failed = []
    for joint in data["joint_names"]:
        output_path = output_dir / f"{joint}.png"
        cmd = [
            sys.executable,
            str(SCRIPT_DIR / "plot_angle.py"),
            str(args.json),
            joint,
            "--output",
            str(output_path),
        ]
        print(f"$ {' '.join(cmd)}", flush=True)
        if subprocess.run(cmd).returncode != 0:
            failed.append(joint)

    print()
    if failed:
        print(f"Done with failures: {failed}", file=sys.stderr)
        return 1
    print(f"Wrote {len(data['joint_names'])} plots to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
