# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
# OCR: Tesseract con idioma español (los acentos y la ñ de los documentos dependen de él)
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 gbd
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .
COPY agents ./agents
COPY dataplane ./dataplane
USER gbd
# Sin secretos en la imagen: Postgres y Foundry se configuran por variables de entorno en tiempo de ejecución.
ENTRYPOINT ["gbd"]
CMD ["api"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1
