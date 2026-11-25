-- 岗位内的 AI 对话：一个岗位一条会话。
--
-- 为什么不做 conversations + messages 两张表：
--   当前需求是"每个岗位一个不被打扰的对话"，一个岗位一个会话就够了。
--   等多会话（一个岗位开多个分析分支）真的需要时再拆表，现在拆是提前抽象。
--
-- 为什么把 role 存成字符串而不是枚举：
--   只有 user / assistant 两种，将来若要存 system 提示词快照也方便。

CREATE TABLE job_chats (
    id         INT PRIMARY KEY AUTO_INCREMENT,
    user_id    INT NOT NULL,
    job_id     INT NOT NULL,
    role       VARCHAR(20) NOT NULL COMMENT 'user / assistant',
    content    MEDIUMTEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_job (user_id, job_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
