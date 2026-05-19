FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# El volumen persistente se monta en /data (ver fly.toml).
# config.py lee DB_PATH del entorno si está definido.
ENV DB_PATH=/data/organizador.db

CMD ["python", "bot.py"]
