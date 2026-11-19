-- 005_add_analysis_fields.sql
-- 日期: 2026-11-17
-- 目的: 存 AI 分析结果（匹配度、分析全文、分析时间）
-- 影响: jobs 新增 3 个可空列，不影响已有数据

ALTER TABLE jobs
    ADD COLUMN match_score INT NULL AFTER note,
    ADD COLUMN analysis TEXT NULL AFTER match_score,
    ADD COLUMN analyzed_at DATETIME NULL AFTER analysis;

