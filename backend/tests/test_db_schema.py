from app.db_schema import CREATE_SESSION_SUMMARIES_TABLE, CREATE_USERS_TABLE, SCHEMA_SQL


def test_schema_includes_expected_users_table_columns():
    assert "CREATE TABLE IF NOT EXISTS users" in CREATE_USERS_TABLE
    assert "password_hash TEXT" in CREATE_USERS_TABLE
    assert "google_id     TEXT        UNIQUE" in CREATE_USERS_TABLE


def test_schema_matches_pg_session_store_shape():
    assert "CREATE TABLE IF NOT EXISTS session_summaries" in CREATE_SESSION_SUMMARIES_TABLE
    assert "data             JSONB       NOT NULL" in CREATE_SESSION_SUMMARIES_TABLE
    assert "CREATE INDEX IF NOT EXISTS idx_ss_tutor_id" in CREATE_SESSION_SUMMARIES_TABLE
    assert "CREATE INDEX IF NOT EXISTS idx_ss_student_id" in CREATE_SESSION_SUMMARIES_TABLE
    assert "CREATE INDEX IF NOT EXISTS idx_ss_start_time" in CREATE_SESSION_SUMMARIES_TABLE
    assert CREATE_SESSION_SUMMARIES_TABLE in SCHEMA_SQL
