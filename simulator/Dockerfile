FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --system --home /app sim
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app.py .
USER sim
EXPOSE 8131
# single process on purpose: simulator state lives in memory
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8131"]
