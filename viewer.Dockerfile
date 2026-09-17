# ClimbCompare static viewer - serves viewer/ (the HTML/JS/CSS frontend,
# plus viewer/data/ and viewer/frames/ once mounted at runtime) on port
# 8000. Deliberately minimal: this is a static file server, not the pipeline
# backend, so it does NOT install requirements.txt (which pulls in
# mediapipe/opencv/scipy/etc. - all dead weight here). rangehttpserver is
# the one dependency actually needed, pinned to match requirements.txt's
# version.
#
# Range-request support specifically matters, not just "some static server":
# the viewer plays video frames and lets the browser request byte ranges of
# large files, which Python's plain http.server doesn't support (confirmed
# locally - it silently breaks video/frame loading). RangeHTTPServer is the
# same drop-in fix already used for local dev.
FROM python:3.12-slim

RUN pip install --no-cache-dir rangehttpserver==1.4.0

# Fixed working directory. The viewer's own JS/HTML use root-relative URLs
# (/viewer/style.css, /viewer/data/pairs.json, /viewer/frames/<label>/...),
# so viewer/ must be served AS A SUBDIRECTORY of whatever's being served -
# copying its contents directly into the served root would break every one
# of those paths.
WORKDIR /app

COPY viewer/ ./viewer/

EXPOSE 8000

CMD ["python", "-m", "RangeHTTPServer", "8000"]
