# ---- build stage: install deps into an isolated prefix ----
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- runtime stage: small image, non-root ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL=sqlite:////data/app.db
RUN useradd --create-home --uid 1000 appuser && mkdir /data && chown appuser /data
COPY --from=builder /install /usr/local
WORKDIR /srv
COPY app ./app
COPY tests ./tests
USER appuser
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
