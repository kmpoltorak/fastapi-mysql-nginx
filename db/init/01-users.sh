#!/bin/bash
# Runs once, on first start with an empty volume (docker-entrypoint-initdb.d).
# Passwords are interpolated into SQL, so keep them alphanumeric (e.g. `openssl rand -hex 16`).
set -e

mysql --protocol=socket -uroot -p"${MYSQL_ROOT_PASSWORD}" <<-EOSQL
	CREATE DATABASE api_auth;
	-- Applications/scripts allowed to call the API (OAuth2 client credentials -> JWT)
	CREATE TABLE api_auth.clients (
	    id INT AUTO_INCREMENT PRIMARY KEY,
	    client_id VARCHAR(64) NOT NULL UNIQUE,
	    secret_hash VARCHAR(255) NOT NULL,
	    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
	);
	-- Users of the application, verified by POST /user/login (password + optional TOTP)
	CREATE TABLE api_auth.users (
	    id INT AUTO_INCREMENT PRIMARY KEY,
	    username VARCHAR(64) NOT NULL UNIQUE,
	    email VARCHAR(255) NOT NULL,
	    password_hash VARCHAR(255) NOT NULL,
	    totp_secret VARCHAR(64) NULL,
	    totp_last_step BIGINT NULL,  -- last accepted TOTP time step, blocks code reuse
	    failed_logins INT NOT NULL DEFAULT 0,
	    locked_until DATETIME NULL,  -- set after too many failed logins
	    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
	);

	-- Clients and users: only rows of the auth tables, no DDL
	CREATE USER 'api_auth'@'%' IDENTIFIED BY '${AUTH_DB_PASSWORD}';
	GRANT SELECT, INSERT, UPDATE, DELETE ON api_auth.* TO 'api_auth'@'%';

	-- Data operations: every database except system and auth ones (needs partial_revokes=ON)
	CREATE USER 'api'@'%' IDENTIFIED BY '${DB_PASSWORD}';
	GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX, REFERENCES,
	      CREATE VIEW, SHOW VIEW, TRIGGER, EVENT, LOCK TABLES, CREATE TEMPORARY TABLES,
	      CREATE ROUTINE, ALTER ROUTINE, EXECUTE, SHOW DATABASES
	      ON *.* TO 'api'@'%';
	REVOKE ALL ON mysql.* FROM 'api'@'%';
	REVOKE ALL ON sys.* FROM 'api'@'%';
	REVOKE ALL ON api_auth.* FROM 'api'@'%';
EOSQL
