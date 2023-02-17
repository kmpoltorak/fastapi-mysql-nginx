FROM python:latest

COPY . /app

WORKDIR /app

RUN apt-get update && apt-get upgrade -yq
RUN apt-get install tzdata -yq
RUN python -m pip install --upgrade pip
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Change timezone for yours
ENV TZ="Europe/Warsaw"

ENV API_KEY="test"

# Mysql database host and credentials
ENV MYSQL_HOST="mysql"
ENV MYSQL_USER="root"
ENV MYSQL_ROOT_PASSWORD="TestDb890"

EXPOSE 8080

CMD ["hypercorn", "app:app", "--bind", "0.0.0.0:8080"]
