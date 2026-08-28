# Deploys as-is to Hugging Face Spaces (Docker SDK), Koyeb, Render or any
# container host. Port 7860 is what Spaces expects; override with PORT elsewhere.
FROM python:3.12-slim

# parselmouth and numpy ship manylinux wheels for 3.12, so no build toolchain
# is needed and the image stays small. Pinning 3.12 rather than tracking latest
# keeps it that way.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860

WORKDIR /app

# Dependencies first so the layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Writable data dir. On a host with no persistent disk, point DB_PATH at a
# managed Postgres instead - audio is never written here in any case, it lives
# in the visitor's own browser.
RUN mkdir -p data && chmod 777 data

EXPOSE 7860

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1"]
