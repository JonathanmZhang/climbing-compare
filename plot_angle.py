"""Plot one joint's angle over time from a compute_angles.py JSON output.

Shows raw (scattered points, gaps where interpolated), interpolated (thin
dashed line), and smoothed (solid line) angle traces together, so gaps,
jitter, and the effect of smoothing are all visible at once for QA.

Usage:
    python plot_angle.py output/attempt_b/attempt_b_angles.json left_elbow
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", type=Path, help="Path to a compute_angles.py JSON output")
    parser.add_argument("joint", help="Joint name to plot (e.g. left_elbow)")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path for the output PNG (default: <alongside input>/joints/<joint>.png)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Also open an interactive matplotlib window",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.json.exists():
        print(f"Error: JSON file not found: {args.json}", file=sys.stderr)
        return 1

    with open(args.json) as f:
        data = json.load(f)

    if args.joint not in data["joint_names"]:
        print(
            f"Error: unknown joint '{args.joint}'. Valid choices: {', '.join(data['joint_names'])}",
            file=sys.stderr,
        )
        return 1

    frames = data["frames"]
    timestamps = [f["timestamp"] for f in frames]
    raw = [f["joints"][args.joint]["raw"] for f in frames]
    interpolated = [f["joints"][args.joint]["interpolated"] for f in frames]
    smoothed = [f["joints"][args.joint]["smoothed"] for f in frames]

    raw_t = [t for t, v in zip(timestamps, raw) if v is not None]
    raw_v = [v for v in raw if v is not None]

    # None -> NaN so matplotlib breaks the line across a gap instead of
    # drawing a straight (and misleading) connector through it.
    interpolated_plot = [np.nan if v is None else v for v in interpolated]
    smoothed_plot = [np.nan if v is None else v for v in smoothed]
    n_null = sum(1 for v in interpolated if v is None)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(timestamps, interpolated_plot, "--", color="tab:orange", linewidth=1, label="interpolated", alpha=0.7)
    ax.plot(timestamps, smoothed_plot, "-", color="tab:blue", linewidth=2, label="smoothed")
    ax.scatter(raw_t, raw_v, color="black", s=10, label="raw", zorder=3)

    if n_null:
        ax.text(
            0.01, 0.02,
            f"{n_null}/{len(frames)} frames have no data (gap too long to interpolate) — shown as gaps",
            transform=ax.transAxes, fontsize=8, color="gray",
        )

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Angle (degrees)")
    ax.set_title(f"{args.joint} angle over time — {data.get('video', args.json.stem)}")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    output_path = args.output or args.json.parent / "joints" / f"{args.joint}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    print(f"Wrote {output_path}", file=sys.stderr)

    if args.show:
        plt.show()

    return 0


if __name__ == "__main__":
    sys.exit(main())
