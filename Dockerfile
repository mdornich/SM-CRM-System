FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SMCRM_DATA_DIR=/data/smcrm \
    PORT=8765

WORKDIR /app

RUN addgroup --system smcrm \
    && adduser --system --ingroup smcrm --home /app smcrm

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts/docker ./scripts/docker

RUN pip install --upgrade pip \
    && pip install .

RUN mkdir -p /data/smcrm/transcripts-inbox \
    /data/smcrm/processed-transcripts \
    /data/smcrm/failed-transcripts \
    /data/smcrm/obsidian-vault \
    /data/smcrm/mock_crm \
    && chown -R smcrm:smcrm /data/smcrm /app

USER smcrm

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.environ.get('PORT','8765'); urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=3).read(1)"

CMD ["scripts/docker/start-review-ui.sh"]
