-- 招聘渠道分组：唯一约束加上 source，并加 source 索引。
--
-- 语义变化：
--   旧 (user_id, company, position)            → 同公司同岗位只能录一条
--   新 (user_id, company, position, source)    → 同公司同岗位在不同渠道可以各录一条
--
-- 为什么这样改：
--   同一个岗位可能在 Boss直聘 看到、又通过本校宣讲会投，这是两条真实的投递记录，
--   渠道不同意味着后续跟进方式不同，合并成一条会丢信息。
--
-- 为什么**不**限制次数（比如最多 3 个渠道）：
--   唯一约束的语义是"禁止完全重复"，不是"允许几次"。要限次数只能应用层 count，
--   而且有并发竞态。第 4 个渠道几乎不会发生，真发生了说明是真实数据，拦住反而错。
--   —— 约束用来防误操作，不用来限制业务行为。
--
-- 现有数据安全：旧约束已经保证 (user_id, company, position) 不重复，
-- 放宽唯一键不会与既有数据冲突。

ALTER TABLE jobs
    DROP INDEX uk_user_company_position,
    ADD CONSTRAINT uk_user_company_position_source
        UNIQUE (user_id, company, position, source),
    ADD INDEX idx_user_source (user_id, source);
