-- 上一次评估的一句话结论。列表接口要回显它，
-- 让用户点进详情就能看到"上次答得怎么样"，不用重新练一遍。
ALTER TABLE interview_answers
    ADD COLUMN last_verdict TEXT NULL COMMENT '最近一次评估结论';
