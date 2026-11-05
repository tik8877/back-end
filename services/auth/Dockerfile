FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir poetry
COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.in-project true && poetry install --only main --no-root --no-interaction

FROM python:3.12-slim
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY common ./common
COPY services ./services
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
CMD ["uvicorn", "services.auth.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
