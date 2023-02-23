# Overview
MySQL on backend with FastAPI on frontend accessed via Nginx created for dev and scientific purposes like learning how to build simple application based on docker microservices. API can be triggered by Postman, curl etc.

# Features
1. Actions on databases
2. Actions on tables
3. Actions on rows - To Do
4. Actions on user - To Do

# Prerequirements
* Docker installed
* Docker compose installed

# Environment variables
In docker-compose.yml you can change environment variables like:
- `MYSQL_HOST`
- `MYSQL_USER`
- `MYSQL_ROOT_PASSWORD`
- `API_KEY`
- `TZ`

# Deploy
- `docker compose build && docker compose up -d`

Recreate after changes:
- `docker compose build && docker compose up -d --force-recreate`

To setup SSL certificate on Nginx:
1. modify configuration in `nginx/fastapi.conf`
2. add certificate and key to the `nginx/` directory
3. add COPY statement to `nginx/Dockerfile`
    `COPY certificate* /etc/ssl/`
4. copy SSL certificate and key files to `/etc/ssl`
5. change/add expose port of Nginx to 443 in docker-compose proxy section

You can add permanent redirection from 80 to 443 to `nginx/fastapi.conf` config file like on example below (to be tested)
```
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}
server {
    listen       443;
    server_name  localhost;
    ssl on;
    ssl_certificate     /etc/ssl/certificate.crt;
    ssl_certificate_key /etc/ssl/certificate_private_key.key;
    location / {
        proxy_pass   http://app:8080;
    }
}
```

Before you use SSL configuration in Nginx remove passphrase from certificate key if exists using OpenSSL

# Example result

```
kmpoltorak@git:~$ docker ps
CONTAINER ID   IMAGE                       COMMAND                  CREATED      STATUS        PORTS                               NAMES
de821c32170d   fastapi-mysql-nginx_proxy   "/docker-entrypoint.…"   4 days ago   Up 23 hours   0.0.0.0:80->80/tcp, :::80->80/tcp   fastapi-mysql-nginx-proxy-1
469beba2fc60   fastapi-mysql-nginx_app     "hypercorn app:app -…"   4 days ago   Up 23 hours   8080/tcp                            fastapi-mysql-nginx-app-1
70687d5a6a2d   mysql:latest                "docker-entrypoint.s…"   4 days ago   Up 23 hours   3306/tcp, 33060/tcp                 fastapi-mysql-nginx-db-1
```

# API requests
API requests can be made by the FastAPI SWAGGER-like GUI or via other tool like curl or Postman. API authentication is based on token provided as environment variable in `docker-compose.yml`

To create table you have to provide it fields params SQL=like, see example data below:
```
{
  "database_name": "test",
  "table_name": "person",
  "columns": [
    {
      "name": "id",
      "params": "int not null auto_increment"
    },
    {
      "name": "name",
      "params": "varchar(255)"
    },
    {
      "name": "surname",
      "params": "varchar(255) not null"
    },
    {
      "name": "primary key",
      "params": "(id)"
    }
  ]
}
```

Output from MySQL database:
```
mysql> show columns from person;
+---------+--------------+------+-----+---------+----------------+
| Field   | Type         | Null | Key | Default | Extra          |
+---------+--------------+------+-----+---------+----------------+
| id      | int          | NO   | PRI | NULL    | auto_increment |
| name    | varchar(255) | YES  |     | NULL    |                |
| surname | varchar(255) | NO   |     | NULL    |                |
+---------+--------------+------+-----+---------+----------------+
3 rows in set (0.02 sec)
```