#!/bin/bash
# Runs once, on first start with an empty volume (docker-entrypoint-initdb.d).
# Passwords are interpolated into SQL, so keep them alphanumeric (e.g. `openssl rand -hex 16`).
set -e

mysql --protocol=socket -uroot -p"${MYSQL_ROOT_PASSWORD}" <<-EOSQL
	CREATE DATABASE api_auth;
	CREATE TABLE api_auth.users (
	    id INT AUTO_INCREMENT PRIMARY KEY,
	    username VARCHAR(64) NOT NULL UNIQUE,
	    email VARCHAR(255) NOT NULL,
	    password_hash VARCHAR(255) NOT NULL,
	    totp_secret VARCHAR(64) NULL,
	    totp_last_step BIGINT NULL,  -- last accepted TOTP time step, blocks code reuse
	    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
	);
	-- Tokens and keys are random 256-bit values, only their SHA-256 is stored
	CREATE TABLE api_auth.refresh_tokens (
	    token_hash CHAR(64) PRIMARY KEY,
	    user_id INT NOT NULL,
	    expires_at DATETIME NOT NULL,
	    FOREIGN KEY (user_id) REFERENCES api_auth.users(id) ON DELETE CASCADE
	);
	CREATE TABLE api_auth.api_keys (
	    id INT AUTO_INCREMENT PRIMARY KEY,
	    user_id INT NOT NULL,
	    name VARCHAR(64) NOT NULL,
	    key_hash CHAR(64) NOT NULL UNIQUE,
	    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	    FOREIGN KEY (user_id) REFERENCES api_auth.users(id) ON DELETE CASCADE
	);

	-- Login/user management: only rows of the auth tables, no DDL
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
