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
- **Stage 5 (Interactive Web Viewer): COMPLETE.** build_viewer_data.py,
  viewer/index.html, and viewer/insights.html built and verified in a live
  browser via Playwright, not just read. Two real bugs found and fixed
  during that verification: (1) seeking a `<video>` element's .currentTime
  on nearly every DTW path step was the actual cause of playback lag, not
  fixable by re-encoding/downscaling alone — replaced with per-frame JPEG
  extraction (build_viewer_data.py) plus canvas drawImage and a rolling
  preload/eviction cache in viewer.js; (2) calling .play() on the video
  elements while also scripting .currentTime made DTW stalls jitter
  instead of freeze cleanly (native playback kept advancing underneath the
  scripted seeks) — fixed by never calling .play(), driving everything
  from the scripted loop instead. "Attempt ended" regions are supplied
  manually per pair (--end-event-a/--end-event-b), not auto-detected —
  there's no reliable signal for this in the joint-angle data alone.
  Serving requires `python -m RangeHTTPServer`, not `http.server`, which
  lacks the Range-request support video/large-file loading needs. True
  upload-and-process was deliberately out of scope for this stage (see
  Stage 6 below).
- **Stage 6 (Live Upload Backend): COMPLETE.** app.py built: `POST /process`
  (accepts two multipart video uploads, sanitizes filenames via werkzeug's
  `secure_filename` plus a stricter `[A-Za-z0-9_-]` collapse matching the
  project's attempt_x naming convention, then runs the full pipeline chain —
  extract_pose.py -> visualize_pose.py -> compute_angles.py per video, then
  align.py -> compute_diff.py -> build_viewer_data.py on the pair) and
  `POST /realign` (re-runs align.py -> compute_diff.py -> build_viewer_data.py
  with `--end-event-a`/`--end-event-b` overrides, for correcting a pair's
  "attempt ended" markers after seeing the initial result — doesn't require
  re-uploading or re-running pose extraction). Matching upload form and
  "mark attempt end" form added to viewer/index.html/viewer.js. Verified
  against a live server, not just read: missing-file and wrong-method
  requests return clean 4xx JSON, a path-traversal payload
  (`../../etc/passwd weird name.MOV`) is neutralized with no file written
  outside videos/, and a full upload-through-the-browser run was confirmed
  producing a viewable result.
- **Stage 7 (Dockerization): COMPLETE.** Two-container architecture,
  coordinated via docker-compose.yml: a `backend` service (Dockerfile)
  running the Flask pipeline (app.py) on port 5000, and a `viewer` service
  (viewer.Dockerfile) running a minimal RangeHTTPServer static file server
  for viewer/ on port 8000 — kept as a separate, much smaller image so it
  doesn't pull in mediapipe/opencv/scipy dead weight just to serve static
  files. Backend's Dockerfile installs libgl1/libglib2.0-0/libsm6/libxext6/
  libxrender1/libgomp1 via apt-get — the system libraries OpenCV and
  MediaPipe need at runtime on Linux even for headless use. Tried switching
  requirements.txt to opencv-contrib-python-headless to avoid needing
  libgl1 at all, but mediapipe==0.10.21's own package metadata hard-requires
  the exact package name opencv-contrib-python (non-headless) regardless of
  what's pinned, so pip installs both side by side — confirmed via a real
  container build. The apt-get libgl1 install is therefore still required,
  not redundant, and this was kept rather than reverted. Four named volumes
  (videos, output, viewer_data, viewer_frames) are shared between both
  services and persist across container restarts/rebuilds — backend writes
  to them (uploads, pipeline output, build_viewer_data.py's per-pair data),
  viewer reads from them to serve results. Two small portability fixes were
  required for this to work at all: app.py's `app.run()` was binding to
  127.0.0.1 by default, unreachable from outside the container despite
  EXPOSE 5000/port mapping — fixed by binding `host="0.0.0.0"` explicitly
  (confirmed unchanged local dev behavior). And viewer.js's hardcoded
  PROCESS_URL/REALIGN_URL constants were replaced with a single
  configurable API_BASE_URL (`window.API_BASE_URL` override, defaulting to
  http://localhost:5000), so the frontend isn't hardwired to one backend
  location. Verified end-to-end against the actual running containers, not
  just a successful build: `docker compose build` produced both images
  cleanly with no import/install errors, `docker compose up` brought up
  both containers reachable on their mapped ports, `GET /process` correctly
  returned 405, and a real two-video upload through the live viewer's
  upload form was confirmed to run the full pipeline inside the backend
  container and produce a working, viewable result in the viewer container.

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

## Current Stage: None — all planned stages complete
Stages 1-7 are complete: pose extraction, joint angles, temporal alignment,
difference computation, the interactive viewer, the live upload backend, and
containerization are all built and verified end-to-end (including a real
upload through the live containers, not just a successful build). No
further stage has been scoped yet.

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
no frontend framework (the viewer itself still reads only precomputed
files). Stage 6 adds Flask for the upload backend. Stage 7 adds Docker/
docker-compose for containerized deployment (separate backend and viewer
images).