-- 003_rename_status_to_yuyue.sql
-- 日期: 2026-11-13
-- 目的: 状态值"面试中"更名为"预约面试"，与 API 层 Literal 对齐
-- 影响: 更新已有数据；不改表结构

UPDATE jobs SET status = '预约面试' WHERE status = '面试中';