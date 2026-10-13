FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==8.3.3
COPY . /tests/
RUN mkdir -p /app /logs/verifier && chmod -R 777 /app /logs
WORKDIR /app
