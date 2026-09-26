# trixie ships the MariaDB 11.8 client; restore needs its --sandbox option
FROM python:3.11-slim-trixie

RUN apt-get update && apt-get upgrade -yq \
    && apt-get install -yq tzdata default-mysql-client \
    && rm -rf /var/lib/apt/lists/* \
    && mysql --help | grep -q -- --sandbox

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root; only /app itself is writable (debug.log)
RUN useradd --system app && chown app /app
USER app

EXPOSE 8080

CMD ["hypercorn", "app:app", "--bind", "0.0.0.0:8080"]
