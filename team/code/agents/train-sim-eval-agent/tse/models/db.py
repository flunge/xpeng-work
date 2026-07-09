CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS experiment (
    id                   TEXT PRIMARY KEY,
    branch               TEXT NOT NULL,
    switches             TEXT NOT NULL,          -- JSON
    binary_id            TEXT,
    sim_task_id          TEXT,
    status               TEXT NOT NULL,
    report_url           TEXT,
    error                TEXT,
    temporal_workflow_id TEXT,
    build_key            TEXT,
    submit_key           TEXT,
    feishu_msg_id        TEXT,
    retry_count          TEXT,                   -- JSON
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experiment_status ON experiment(status);
CREATE INDEX IF NOT EXISTS idx_experiment_build_key ON experiment(build_key);
CREATE INDEX IF NOT EXISTS idx_experiment_submit_key ON experiment(submit_key);
"""
