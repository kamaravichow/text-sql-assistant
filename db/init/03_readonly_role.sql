-- The agent connects with a read-only role: defence in depth next to the SQL validator.
CREATE ROLE analyst_ro LOGIN PASSWORD 'analyst_ro';
DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO analyst_ro', current_database()); END $$;
GRANT USAGE ON SCHEMA public TO analyst_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analyst_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO analyst_ro;
ALTER ROLE analyst_ro SET default_transaction_read_only = on;
