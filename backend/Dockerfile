FROM python:3.12.8-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock requirements-dev.lock ./
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.lock; else pip install -r requirements.lock; fi
COPY . .
# Непривилегированный пользователь
RUN useradd --system --uid 10001 app && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-server-header"]
