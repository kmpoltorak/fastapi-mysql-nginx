# FastAPI + MySQL + Nginx Microservice

This project is a simple microservice stack for development and learning purposes. It provides a REST API (FastAPI) for MySQL database management, served behind Nginx. All services are containerized with Docker Compose.

## Features

- Database management: create, list, delete, backup, restore
- Table management: create, list, delete, rename, describe columns
- Row management: insert, get, update, delete
- User management: create, get, update, delete (in-memory demo)
- API authentication via token (header: `AccessToken`)
- Linting (flake8) and tests (pytest), run in GitHub Actions CI

## Requirements

- Docker
- Docker Compose

## Environment Variables

Copy `.env.example` to `.env` and adjust values (Docker Compose reads it automatically; defaults are used when unset):

- `MYSQL_HOST` - MySQL host (default: db)
- `MYSQL_USER` - MySQL user (default: root)
- `MYSQL_ROOT_PASSWORD` - MySQL root password
- `API_KEY` - API authentication token
- `TZ` - Timezone

## Deployment

Build and start all services:

```
docker compose build && docker compose up -d
```

Rebuild after changes:

```
docker compose build && docker compose up -d --force-recreate
```

## Nginx SSL Setup (optional)

1. Edit `nginx/fastapi.conf` for SSL configuration
2. Add your certificate and key to the `nginx/` directory
3. Add to `nginx/Dockerfile`:
   ```
   COPY certificate* /etc/ssl/
   ```
4. Expose port 443 in the `proxy` service in `docker-compose.yml`
5. (Optional) Add HTTP->HTTPS redirect in `nginx/fastapi.conf`:
   ```
   server {
       listen 80;
       server_name _;
       return 301 https://$host$request_uri;
   }
   ```

**Note:** Remove passphrase from your certificate key if present (see OpenSSL docs).

## Example: Running Containers

After starting the services, check running containers:
```sh
$ docker ps
CONTAINER ID   IMAGE                       COMMAND                  ...
...           fastapi-mysql-nginx_proxy   ...
...           fastapi-mysql-nginx_app     ...
...           mysql:8.3                   ...
```

## API Usage

You can use the FastAPI Swagger UI (available at `/`) or tools like curl/Postman. All endpoints except `/health` require the `AccessToken` header with the value set to your `API_KEY`.

### Example: Create Table

Request:
```
POST /table/create
{
  "database_name": "test",
  "table_name": "person",
  "columns": [
    { "name": "id", "params": "int not null auto_increment primary key" },
    { "name": "name", "params": "varchar(255)" },
    { "name": "surname", "params": "varchar(255) not null" }
  ]
}
```

Result in MySQL:
```
mysql> show columns from person;
+---------+--------------+------+-----+---------+----------------+
| Field   | Type         | Null | Key | Default | Extra          |
+---------+--------------+------+-----+---------+----------------+
| id      | int          | NO   | PRI | NULL    | auto_increment |
| name    | varchar(255) | YES  |     | NULL    |                |
| surname | varchar(255) | NO   |     | NULL    |                |
+---------+--------------+------+-----+---------+----------------+
```

### Database Backup & Restore

**Backup:**
```
POST /database/backup
{
  "database_name": "testdb"
}
```
Response: SQL dump string in `data` field.

**Restore:**
```
POST /database/restore
{
  "database_name": "testdb",
  "sql_dump": "CREATE TABLE ...; INSERT INTO ...; ..."
}
```

**Note:** The SQL dump must be valid MySQL SQL. The operation is executed directly on the database.

## Linting & Tests

Tests mock the database, so no MySQL is needed:

```
pip install -r app/requirements.txt flake8 pytest httpx
flake8 app
cd app && python -m pytest
```
