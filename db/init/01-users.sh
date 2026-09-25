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
	    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
	);

	-- Login/user management: only the users table
	CREATE USER 'api_auth'@'%' IDENTIFIED BY '${AUTH_DB_PASSWORD}';
	GRANT SELECT, INSERT, UPDATE, DELETE ON api_auth.users TO 'api_auth'@'%';

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
