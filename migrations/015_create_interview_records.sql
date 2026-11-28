-- 面试复盘：真实被问到的问题 + 我当时答得怎么样。
--
-- 为什么值得单独建表：
--   这是产品里唯一"真实发生过"的数据。预测题是模型猜的，
--   面经是别人说的，只有这里记的是你亲耳听到的问题。
--   攒够之后它就是**你自己的题库**，比任何面经都准。
--
-- 为什么问题单独一张表（而不是塞进 JSON 列）：
--   将来最有价值的用法是"跨岗位看所有被问过的 Redis 问题"，
--   JSON 列做不到聚合查询。趁现在只有几条记录，把它做对。
--
-- 关于"一个岗位只能记一次面试"这个已知限制：
--   本表按"一次面试一行"设计，天然支持多次（用 interview_at 区分）。
--   但界面上**不做轮次管理**（不搞第几面、每轮独立状态机），
--   所以那个复杂问题仍未解决，只是不再被表结构卡死。
--   round_no 先留着，等真要做轮次时不用改表。

CREATE TABLE interview_records (
    id           INT PRIMARY KEY AUTO_INCREMENT,
    user_id      INT NOT NULL,
    job_id       INT NOT NULL,
    interview_at DATETIME NULL COMMENT '面试时间',
    round_no     INT NOT NULL DEFAULT 1 COMMENT '第几轮，暂时恒为 1',
    outcome      VARCHAR(20) NOT NULL DEFAULT 'pending'
                 COMMENT 'pending 待结果 / passed 通过 / failed 挂了 / no_reply 没回音',
    summary      TEXT NULL COMMENT '整体反思',
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_job (user_id, job_id),
    INDEX idx_user_time (user_id, interview_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE interview_questions (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    user_id     INT NOT NULL,
    record_id   INT NOT NULL,
    question    TEXT NOT NULL COMMENT '面试官原话',
    my_answer   TEXT NULL COMMENT '我当时怎么答的',
    performance VARCHAR(10) NOT NULL DEFAULT 'ok'
                COMMENT 'good 答得好 / ok 一般 / bad 答不上来',
    gap         TEXT NULL COMMENT '该补什么',
    follow_up   TEXT NULL COMMENT '追问',
    order_no    INT NOT NULL DEFAULT 0,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_record (record_id),
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
