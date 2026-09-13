# Climbing Video Comparison Tool

## Project Goal
Compare two videos of the same climber attempting the same route, to visualize
differences in body movement between attempts (similar in spirit to golf swing
comparison apps).

## Progress So Far
- **Stage 1 (Pose Extraction Pipeline): COMPLETE.** extract_pose.py,
  visualize_pose.py, batch_extract.py, and analyze_detection.py are built and
  working. Output is organized per-attempt: output/<attempt_name>/ contains
  that attempt's JSON, overlay video, angles JSON, and joints/ plot folder.
- **Stage 2 (Joint Angle Computation): COMPLETE.** compute_angles.py and
  plot_angle.py/plot_all_joints.py built and verified. Includes
  --max-gap-seconds so long occlusion gaps are marked null instead of being
  flat-extrapolated.
- **Stage 3 (Temporal Alignment): COMPLETE.** align.py built using DTW with
  masked distance (only compares joints valid in both frames at that step)
  and per-pair joint exclusion (a joint is dropped entirely for a video pair
  if it's null in more than 50% of either video's frames). Found and fixed a
  real bug: the masked distance originally SUMMED differences across valid
  joints instead of averaging, which made frames with fewer valid joints
  look artificially "cheap" to match against almost anything — DTW got
  stuck on a single frame for a 6.45-second stretch as a result. Fixed by
  averaging instead of summing, plus adding a high penalty distance for any
  frame pair with fewer than --min-valid-joints (default 4) mutually-valid
  joints. Verified visually (not just numerically) via sidebyside_aligned.py
  against real footage (attempt_f vs attempt_g) — confirmed matching body
  positions at multiple aligned timestamp pairs.
- **Stage 4 (Difference Computation): COMPLETE.** compute_diff.py built —
  computes per-joint and total divergence scores at each aligned step, using
  the same masking philosophy as align.py (never invent data for a missing
  joint). Added --max-stall-length to locally excise steps belonging to a
  DTW stall (one video's frame stuck while the other advances), resuming
  normal inclusion once the stall ends — a targeted fix, not a blunt
  truncation, since stalls can occur anywhere in the path, not just near the
  end. Two real findings validated against actual footage on attempt_f vs
  attempt_g:
  1. A genuine divergence spike at 3.5-5.0s (~22°) — climber kept feet on
     the wall in one attempt, cut feet in the other, during the same move.
  2. A large divergence spike near 18.5s that is NOT a stall (both videos
     advance normally through it) — traced to attempt_f falling/ending its
     climb at ~18.5s while attempt_g continues climbing until ~23s before
     its own fall. This matches the known "attempts diverge in outcome"
     DTW limitation below: past this point the two climbs aren't really
     comparable, and this should be labeled as an "attempt ended" event in
     any display, not shown as an unexplained divergence spike.

## Footage notes and joint reliability findings
- attempt_a.mp4: severe tracking dropout (60%), confirmed footage-specific
  problem. Excluded from use.
- attempt_b.mp4 (angled camera): right_elbow/right_shoulder/right_hip/
  right_knee poorly tracked (67-80% null); left side and torso_lean reliable.
- attempt_e.mp4 (square-on, closer): right arm much improved vs. attempt_b
  (8% null), but left_hip/left_knee got worse (34-41% null) and right leg
  stayed bad — a temporary mid-clip occlusion (foot/ankle out of view during
  a specific move), not a framing problem.
- attempt_f.mp4 and attempt_g.mp4 (same route, same camera angle, real
  comparison pair): consistent pattern in BOTH clips — left_hip and
  left_knee are the worst-tracked joints (62-80% null), right_hip/right_knee
  moderately unreliable (46-49% null), torso_lean/right_elbow/right_shoulder
  reliable (75-100% good), left_elbow/left_shoulder moderately reliable.
  align.py excluded left_hip and left_knee per the 50% threshold for this
  pair; the remaining 7 joints were used.
- Takeaway: no single joint is reliable across all footage. Reliability
  must be assessed per video pair, not assumed globally. torso_lean is the
  only joint reliable in every clip so far.

## Current Stage: Stage 5 — Interactive Web Viewer
A static, no-backend HTML/JS viewer that reads precomputed pipeline output
(alignment path, divergence scores, video files) and lets the user watch
two attempts synced side by side, plus a separate insights page with
summary stats.

## Requirements for this stage

### Main viewer page
- Static data.json per attempt pair, combining: alignment path, per-step
  divergence scores, joints used/excluded, video file paths
- An attempt-pair PICKER (dropdown or list), not true video upload — lets
  the user choose among already-processed pairs (e.g. f vs g, b vs e).
  True upload-and-process is explicitly out of scope for now (would
  require a backend to run the full Python pipeline live) — note this as
  a future direction, not a current feature
- Two videos side by side, synced via the alignment path (not real time),
  each with its own displayed timestamp
- Shared play/pause and scrub control
- A divergence-over-time graph beneath the videos
- Any point where one video's frames stall, or one attempt effectively
  ends (per the Stage 4 findings above), shown as a labeled region
  ("attempt ended" / "divergence"), not an unexplained spike
- A right-arrow / nav control to the insights page

### Insights page (second screen)
- Summary stat cards: average divergence, biggest single divergence moment
  (value + timestamp), how many joints were actually compared
- Per-joint divergence breakdown (bar per joint, sorted by magnitude)
- For the single biggest divergence moment: extract and show a frame
  screenshot from each video at that timestamp, side by side

## Known challenges to keep in mind
- Climbing footage has more occlusion than typical use cases. No joint can
  be assumed reliable without checking per video pair.
- DTW will always produce *an* alignment even if the underlying data is
  poor — a low-confidence result won't look different from a good one
  without manually checking it against known-matching mome3s in both
  videos. Confirmed the hard way in Stage 3.
- If two attempts diverge significantly (e.g. one falls, one doesn't), DTW
  will still force some alignment past that point — not meaningful for
  comparison purposes, but IS meaningful as a "these attempts ended
  differently" signal. Confirmed in Stage 4 with real footage (attempt_f
  fell at ~18.5s, attempt_g continued to ~23s). Should be surfaced as a
  labeled event in the viewer, not filtered out or hidden.

## Tech stack
Python, OpenCV for video I/O, MediaPipe for pose estimation, scipy for
smoothing filters, dtaidistance for DTW. Stage 5 viewer: static HTML/JS,
no backend, no frontend framework.