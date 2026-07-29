FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY univoice_worker ./univoice_worker

RUN useradd --create-home --uid 10001 univoice
USER univoice

CMD ["python", "-m", "univoice_worker.main"]
