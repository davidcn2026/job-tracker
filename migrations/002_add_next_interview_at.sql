-- 002_add_next_interview_at.sql
-- 日期: 2026-11-13
-- 目的: 记录"下次面试时间"，供列表排序与提醒
-- 影响: jobs 新增一列（可空，不影响已有数据）

ALTER TABLE jobs
  ADD COLUMN next_interview_at DATETIME NULL AFTER published_at;