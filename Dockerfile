FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=poll \
    STREAMLIT_SERVER_RUN_ON_SAVE=true

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        git \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md app.py /app/
COPY src /app/src

RUN pip install --upgrade pip \
    && pip install -e ".[dev]"

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
