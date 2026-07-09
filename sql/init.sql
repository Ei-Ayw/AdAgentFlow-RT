-- AdAgentFlow 完整数据库 schema
-- 所有表带 created_at / updated_at ，方便时序聚合
-- 注意：ORM 也会建表，但这里提供原生 SQL 视图，方便后期调试

-- ============================================================
-- 1. tasks 表：任务主信息
-- ============================================================
CREATE TABLE IF NOT EXISTS tasks (
    id BIGSERIAL PRIMARY KEY,
    task_id VARCHAR(64) UNIQUE NOT NULL,
    status VARCHAR(32) NOT NULL,
    product_name VARCHAR(255),
    platform VARCHAR(64),
    style VARCHAR(128),
    duration INT,
    target_user VARCHAR(255),
    selling_points JSONB DEFAULT '[]'::jsonb,
    input_payload JSONB,
    output_payload JSONB,
    retry_count INT DEFAULT 0,
    max_retry INT DEFAULT 3,
    trace_id VARCHAR(64),
    last_failure_reason VARCHAR(128),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_trace_id ON tasks(trace_id);
CREATE INDEX idx_tasks_created_at ON tasks(created_at DESC);

-- ============================================================
-- 2. task_steps 表：每个 Agent 节点状态
-- ============================================================
CREATE TABLE IF NOT EXISTS task_steps (
    id BIGSERIAL PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    step_id VARCHAR(64) NOT NULL,
    step_name VARCHAR(128),
    status VARCHAR(32),
    input_payload JSONB,
    output_payload JSONB,
    retry_count INT DEFAULT 0,
    failure_reason VARCHAR(128),
    error_message TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    latency_ms INT,
    token_cost INT DEFAULT 0,
    model_name VARCHAR(128),
    prompt_version VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, step_id)
);

CREATE INDEX idx_steps_task_id ON task_steps(task_id);
CREATE INDEX idx_steps_status ON task_steps(status);
CREATE INDEX idx_steps_failure ON task_steps(failure_reason);

-- ============================================================
-- 3. task_traces 表：全链路追踪事件
-- ============================================================
CREATE TABLE IF NOT EXISTS task_traces (
    id BIGSERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    task_id VARCHAR(64),
    step_id VARCHAR(64),
    event_type VARCHAR(64),
    event_status VARCHAR(32),
    latency_ms INT,
    model_name VARCHAR(128),
    prompt_version VARCHAR(64),
    token_cost INT,
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_traces_trace_id ON task_traces(trace_id);
CREATE INDEX idx_traces_task_id ON task_traces(task_id);
CREATE INDEX idx_traces_event_type ON task_traces(event_type);

-- ============================================================
-- 4. dead_letters 表：死信队列
-- ============================================================
CREATE TABLE IF NOT EXISTS dead_letters (
    id BIGSERIAL PRIMARY KEY,
    task_id VARCHAR(64),
    step_id VARCHAR(64),
    failure_reason VARCHAR(128),
    input_payload JSONB,
    last_output JSONB,
    retry_count INT,
    error_message TEXT,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dead_resolved ON dead_letters(resolved);
CREATE INDEX idx_dead_task_id ON dead_letters(task_id);

-- ============================================================
-- 5. evaluation_results 表：LLM-as-Judge 结果
-- ============================================================
CREATE TABLE IF NOT EXISTS evaluation_results (
    id BIGSERIAL PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    step_id VARCHAR(64),
    score INT,
    passed BOOLEAN,
    issues JSONB,
    risk_level VARCHAR(32),
    suggested_fix TEXT,
    evaluator_model VARCHAR(128),
    prompt_version VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_evaluations_task_id ON evaluation_results(task_id);
CREATE INDEX idx_evaluations_passed ON evaluation_results(passed);

-- ============================================================
-- 6. message_dedup_records 表：消息去重
-- ============================================================
CREATE TABLE IF NOT EXISTS message_dedup_records (
    id BIGSERIAL PRIMARY KEY,
    message_id VARCHAR(128) UNIQUE NOT NULL,
    task_id VARCHAR(64),
    step_id VARCHAR(64),
    consumed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dedup_task_id ON message_dedup_records(task_id);

-- ============================================================
-- 7. agent_metrics 表：节点级指标聚合
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_metrics (
    id BIGSERIAL PRIMARY KEY,
    step_name VARCHAR(128) UNIQUE NOT NULL,
    total_executions BIGINT DEFAULT 0,
    success_executions BIGINT DEFAULT 0,
    failed_executions BIGINT DEFAULT 0,
    retry_executions BIGINT DEFAULT 0,
    total_latency_ms BIGINT DEFAULT 0,
    total_token_cost BIGINT DEFAULT 0,
    json_failures BIGINT DEFAULT 0,
    schema_failures BIGINT DEFAULT 0,
    last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
