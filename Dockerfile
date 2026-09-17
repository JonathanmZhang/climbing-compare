# ClimbCompare Flask backend (app.py) - accepts video uploads and runs the
# pose-comparison pipeline on them. Base image version matches this
# project's actual development environment (.venv was built with Python
# 3.12.3; no .python-version/pyproject.toml exists to pin it explicitly).
FROM python:3.12-slim

# System libraries OpenCV (opencv-contrib-python / -headless) and MediaPipe
# need at runtime on Linux, even for headless use. Both opencv variants end
# up installed regardless of the requirements.txt pin, since mediapipe's own
# package metadata hard-requires the non-headless opencv-contrib-python
# alongside it - so these are genuinely needed, not a defensive guess.
# Installed and cleaned up in a single layer to keep image size down.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Fixed working directory - app.py and every pipeline script it shells out
# to (extract_pose.py, visualize_pose.py, compute_angles.py, align.py,
# compute_diff.py, build_viewer_data.py) resolve videos/, output/,
# viewer/data/, and viewer/frames/ relative to the current working
# directory, not to their own file location. This must never change after
# being set, or those paths resolve to the wrong place.
WORKDIR /app

# Install dependencies before copying source, so this layer stays cached
# across rebuilds that only change application code.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the application code. videos/, output/, viewer/data/, and
# viewer/frames/ are excluded via .dockerignore - they're runtime-generated
# data, not part of the image.
COPY . .

# Runtime data that must persist across container restarts/rebuilds - the
# exact paths process_video() (in app.py) and build_viewer_data.py check
# for existing output and write new output into.
VOLUME ["/app/videos", "/app/output", "/app/viewer/data", "/app/viewer/frames"]

EXPOSE 5000

CMD ["python", "app.py"]
