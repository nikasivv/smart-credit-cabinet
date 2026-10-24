FROM python:3.12.8-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY requirements.lock .
RUN pip install -r requirements.lock
COPY . .
RUN useradd --system --uid 10002 mock && chown -R mock /srv
USER mock
EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health')" || exit 1
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
