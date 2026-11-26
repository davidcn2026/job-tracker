-- 面试题的作答记录：答案、AI 评估结果、追问进度、错题状态。
--
-- 为什么不用 jobs.interview_prep 那个 JSON 存答案：
--   重新生成面试题（改 JD / 改简历 force）会把 JSON 整个覆盖，
--   用户辛苦写的答案会全丢。答案必须独立于"题目"存在。
--
-- 为什么用 question_hash 而不是题号：
--   重新生成后题目顺序会变，用题号会错位。
--   题目文本不变 → hash 不变 → 答案能找回来。
--
-- status：
--   untried   没练过
--   tried     练过了（可能是中途停）
--   partial   部分掌握（深挖到第 3 层才卡住）
--   mastered  已掌握（关键点基本都覆盖）
--   wrong     完全不会（用户点「我不会」）

CREATE TABLE interview_answers (
    id            INT PRIMARY KEY AUTO_INCREMENT,
    user_id       INT NOT NULL,
    job_id        INT NOT NULL,
    question_hash VARCHAR(16) NOT NULL,
    answer        TEXT NULL COMMENT '用户最近一次的回答',
    covered       JSON NULL COMMENT '说到且正确的关键点下标',
    wrong         JSON NULL COMMENT '提到但理解错的：[{index, why}]',
    missing       JSON NULL COMMENT '完全没提到的关键点下标',
    depth         INT NOT NULL DEFAULT 0 COMMENT '已追问层数（上限 3）',
    transcript    JSON NULL COMMENT '[{layer, question, answer}]',
    finish_reason VARCHAR(20) NULL COMMENT 'model / max_depth / user_done / user_give_up',
    status        VARCHAR(20) NOT NULL DEFAULT 'untried',
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_job_q (user_id, job_id, question_hash),
    INDEX idx_user_status (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
