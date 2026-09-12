"""Plot total divergence over time from a compute_diff.py JSON output.

X-axis is timestamp_a (video_a's own elapsed time, monotonic along the
alignment path) - the most natural "time in the climb" reference. Steps
with no valid joints (total_divergence null) show as gaps in the line
rather than being interpolated or silently dropped.

Usage:
    python plot_divergence.py output/attempt_f_vs_attempt_g_divergence.json
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("divergence_json", type=Path, help="Path to a compute_diff.py JSON output")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path for the output PNG (default: <alongside input>/<stem>.png)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Also open an interactive matplotlib window",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.divergence_json.exists():
        print(f"Error: JSON file not found: {args.divergence_json}", file=sys.stderr)
        return 1

    with open(args.divergence_json) as f:
        data = json.load(f)

    steps = data["steps"]
    timestamps_a = [s["timestamp_a"] for s in steps]
    totals = [np.nan if s["total_divergence"] is None else s["total_divergence"] for s in steps]

    n_null = sum(1 for s in steps if s["total_divergence"] is None)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(timestamps_a, totals, "-", color="tab:red", linewidth=1.5)

    ax.set_xlabel("video_a elapsed time (s)")
    ax.set_ylabel("Total divergence (mean abs. angle diff, degrees)")
    ax.set_title(
        f"Divergence over time — {data.get('video_a', '?')} vs {data.get('video_b', '?')}\n"
        f"joints used: {', '.join(data['joints_used'])}"
    )
    ax.grid(True, alpha=0.3)

    if n_null:
        ax.text(
            0.01, 0.02,
            f"{n_null}/{len(steps)} steps had no valid joints — shown as gaps",
            transform=ax.transAxes, fontsize=8, color="gray",
        )

    fig.tight_layout()

    output_path = args.output or args.divergence_json.parent / f"{args.divergence_json.stem}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    print(f"Wrote {output_path}", file=sys.stderr)

    if args.show:
        plt.show()

    return 0


if __name__ == "__main__":
    sys.exit(main())
