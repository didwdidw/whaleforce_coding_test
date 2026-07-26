# Deployment image for Task 1.
#
# Based on Playwright's official Python image: it ships Chromium together with the shared
# libraries the browser needs, which a stock Python image does not. Zeabur's language
# auto-detection would pick that stock image and produce a container where the browser
# cannot start, so this Dockerfile is explicit rather than inferred.
#
# The tag pins the runtime. Keep the Playwright version here and in requirements.txt in
# step — a mismatch between the library and the bundled browser build is a startup failure.
FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

# Fail fast and unbuffered, so container logs show a crash as it happens.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Browsers are already in the image; verify rather than trust, so a base-image change that
# drops Chromium fails the build instead of the first run.
RUN python -c "from playwright.sync_api import sync_playwright; \
    p = sync_playwright().start(); b = p.chromium.launch(); \
    print('chromium ok:', b.version); b.close(); p.stop()"

COPY preflight/ ./preflight/

# The app itself is added as M1 lands; the image is built now because M0.1's RAM figure has
# to be measured inside it to describe what production actually runs.

CMD ["python", "-c", "print('image ready; no entrypoint yet (M1 pending)')"]
