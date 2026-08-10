FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY univoice_worker ./univoice_worker
# STT 전공 용어 교정에 쓰는 lexicon_*.json. 없으면 교정이 조용히 비활성된다.
COPY rag_assets ./rag_assets

RUN useradd --create-home --uid 10001 univoice
USER univoice

CMD ["python", "-m", "univoice_worker.main"]
