-- 006_add_verdict.sql
-- 日期: 2026-11-18
-- 目的: 存 AI 给出的投递建议档位，支持按档位筛选
-- 影响: jobs 新增 1 个可空列 + 1 个索引

ALTER TABLE jobs
    ADD COLUMN verdict VARCHAR(20) NULL AFTER analysis;

ALTER TABLE jobs
    ADD INDEX idx_user_verdict (user_id, verdict);