FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[ui,openai]"

COPY docs ./docs
COPY eval ./eval

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000 8501

# API by default; the compose file overrides the command for the Streamlit service.
CMD ["uvicorn", "sqlagent.api.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
