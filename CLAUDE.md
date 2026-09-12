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
  joints, so low-confidence pairs are actively discouraged rather than
  accidentally rewarded. Verified visually, not just numerically: rendered
  a synced side-by-side video (sidebyside_aligned.py) at the corrected
  alignment and confirmed matching body positions at multiple aligned
  timestamp pairs on real footage (attempt_f vs attempt_g).

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
  This consistency across two independent attempts of the same route
  suggests a structural cause (climber's left side or a route feature
  facing away from camera), not random noise. For attempt_f vs attempt_g,
  align.py excluded left_hip and left_knee per the 50% threshold; the
  remaining 7 joints were used.
- Takeaway: no single joint is reliable across all footage. Reliability
  must be assessed per video pair, not assumed globally. torso_lean is the
  only joint reliable in every clip so far.

## Current Stage: Stage 4 — Difference Computation

Using the aligned frame pairs from align.py's output, compute per-joint and
total divergence scores between the two attempts at each aligned point.

## Requirements for this stage

- Input: an align.py alignment JSON (path of frame_a/frame_b pairs) plus
  both attempts' compute_angles.py JSON outputs
- For each step in the alignment path, compute the absolute difference in
  each joint's smoothed angle between frame_a and frame_b
- Only compute a difference for a joint if it's valid (non-null) in BOTH
  frames — reuse the same masking philosophy as align.py, don't invent
  data for missing joints
- Aggregate into a total divergence score per aligned step (e.g. mean
  absolute difference across valid joints at that step), plus per-joint
  divergence values, so both "how different overall" and "which joint
  differs most" are available
- Output a JSON file with, per aligned step: timestamp_a, timestamp_b,
  total divergence score, and per-joint divergence values (null where a
  joint wasn't comparable at that step)
- Also build a plotting script showing total divergence over time, for
  visual verification (divergence should spike at genuinely different
  moments and stay low where the two attempts look similar)

## Known challenges to keep in mind

- Climbing footage has more occlusion than typical use cases. No joint can
  be assumed reliable without checking per video pair.
- DTW will always produce _an_ alignment even if the underlying data is
  poor — a low-confidence result won't look different from a good one
  without manually checking it against known-matching moments in both
  videos. This was confirmed the hard way in Stage 3; the same caution
  applies to interpreting divergence scores in Stage 4 — a high or low
  score is only meaningful where the underlying joints were actually valid.
- If two attempts diverge significantly (e.g. one falls, one doesn't), DTW
  will still force some alignment past that point — not meaningful, a known
  limitation, not a bug to fix.

## Tech stack

Python, OpenCV for video I/O, MediaPipe for pose estimation, scipy for
smoothing filters, dtaidistance for DTW.
