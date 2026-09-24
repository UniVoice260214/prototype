FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/cache/huggingface

WORKDIR /app

COPY requirements.txt requirements-runtime.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch
RUN pip install --no-cache-dir --requirement requirements-runtime.txt

COPY src ./src
COPY tools ./tools
COPY data/raw ./data/raw

RUN useradd --create-home --uid 10001 univoice \
    && mkdir -p /app/data/chunks /app/indexes /cache/huggingface \
    && chown -R univoice:univoice /app /cache

USER univoice
EXPOSE 8000

CMD ["uvicorn", "server:app", "--app-dir", "/app/src", "--host", "0.0.0.0", "--port", "8000"]
