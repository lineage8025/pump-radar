FROM python:3.12-slim
RUN pip install --no-cache-dir ccxt pandas pyarrow
WORKDIR /app
COPY scripts/ /app/scripts/
