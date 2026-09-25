FROM python:3.11-slim

RUN apt-get update && apt-get upgrade -yq \
    && apt-get install -yq tzdata default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["hypercorn", "app:app", "--bind", "0.0.0.0:8080"]
