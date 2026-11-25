-- 修正 008 的方向偏差：助手是「全局唯一的岗位库管理员」，不是「每个岗位一个对话」。
--
-- 008 建的 job_chats 按 job_id 分会话，导致"每张卡片里一个小 AI"，
-- 与产品定位（模型承担助手 / 客服角色，能看整个岗位库）相反。
-- 该表刚建、从未写入数据，直接废弃。
DROP TABLE IF EXISTS job_chats;

-- 全局助手消息表：一个用户一条会话线。
-- role: user / assistant / tool
--   tool 消息用于把"我搜了什么、搜到几条"显式记录下来，
--   让用户看得见助手的动作，而不是黑箱。
CREATE TABLE assistant_messages (
    id         INT PRIMARY KEY AUTO_INCREMENT,
    user_id    INT NOT NULL,
    role       VARCHAR(20) NOT NULL COMMENT 'user / assistant / tool',
    content    MEDIUMTEXT NOT NULL,
    tool_name  VARCHAR(50) NULL COMMENT 'role=tool 时记录工具名',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
