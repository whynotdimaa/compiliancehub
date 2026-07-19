-- Non-superuser application role.
--
-- POSTGRES_USER (compliance) is a SUPERUSER — superusers bypass Row-Level
-- Security entirely, even with FORCE ROW LEVEL SECURITY. The API and workers
-- therefore connect as app_user; the superuser is only for migrations.
-- Runs once at cluster init (docker-entrypoint-initdb.d), as `compliance`.

CREATE ROLE app_user LOGIN PASSWORD 'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;

GRANT CONNECT ON DATABASE compliancehub TO app_user;
GRANT USAGE ON SCHEMA public TO app_user;

-- Tables are created later by Alembic (as compliance), so grant via default
-- privileges instead of on existing objects.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_user;
