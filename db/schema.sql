CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL UNIQUE,
    text_hash CHAR(64) NOT NULL UNIQUE,
    text TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    tags TEXT[] NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT 'api',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_category ON documents (category);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_tags ON documents USING GIN (tags);

CREATE TABLE IF NOT EXISTS vector_sync_states (
    document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
    vector_backend TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT,
    indexed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, vector_backend),
    CONSTRAINT vector_sync_states_status_check
        CHECK (status IN ('pending', 'indexed', 'failed', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_vector_sync_states_backend_status
    ON vector_sync_states (vector_backend, status);

CREATE TABLE IF NOT EXISTS import_jobs (
    job_id TEXT PRIMARY KEY,
    source_filename TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    inserted INTEGER NOT NULL DEFAULT 0,
    existing_count INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    failed_rows_download_url TEXT,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_import_jobs_created_at ON import_jobs (created_at DESC);

CREATE TABLE IF NOT EXISTS search_logs (
    id BIGSERIAL PRIMARY KEY,
    backend TEXT NOT NULL DEFAULT '',
    query TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_search_logs_created_at ON search_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_search_logs_backend_created_at ON search_logs (backend, created_at DESC);

CREATE TABLE IF NOT EXISTS app_errors (
    id BIGSERIAL PRIMARY KEY,
    backend TEXT NOT NULL DEFAULT '',
    operation TEXT NOT NULL DEFAULT '',
    surface TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_app_errors_created_at ON app_errors (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_errors_backend_created_at ON app_errors (backend, created_at DESC);

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    event TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    actor TEXT NOT NULL DEFAULT '',
    backend TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    client_ip TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL DEFAULT '',
    target_id TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT audit_logs_level_check
        CHECK (level IN ('debug', 'info', 'warning', 'error', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_backend_created_at ON audit_logs (backend, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_event_created_at ON audit_logs (event, created_at DESC);
