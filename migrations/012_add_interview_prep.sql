-- 面试准备（预测问题 + 参考答案 + 弱点标注），存成 JSON。
--
-- 为什么存下来而不是每次现生成：
--   生成一次要约 15~25 秒、几千 token。用户会反复回来复习，
--   每次都重新生成纯属浪费。JD 或简历变了才需要重新生成。
--
-- 与 jobs.analysis 的设计一致：JSON 存在一列里，
-- 需要结构化字段时由应用层解析（不拆表，避免为一次性结果建一堆列）。

ALTER TABLE jobs
    ADD COLUMN interview_prep MEDIUMTEXT NULL COMMENT '面试准备 JSON',
    ADD COLUMN interview_prep_at DATETIME NULL COMMENT '生成时间';
