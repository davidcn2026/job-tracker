-- 补上 interview_questions → interview_records 的外键。
--
-- 迁移 015 只建了普通 INT 列，没加 FOREIGN KEY，导致 SQLAlchemy 在配置
-- InterviewRecord.questions 关系时抛 NoForeignKeysError：
--   没有外键，ORM 无法确定父子表的连接条件
--
-- ON DELETE CASCADE 与模型里的 cascade="all, delete-orphan" 对齐：
-- 删一次面试记录，它下面的问题行应该一起消失，不留孤儿数据。

ALTER TABLE interview_questions
    ADD CONSTRAINT fk_iq_record
        FOREIGN KEY (record_id) REFERENCES interview_records (id) ON DELETE CASCADE;
