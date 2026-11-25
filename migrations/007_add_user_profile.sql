-- 用户简历：存「解析后的纯文本」，供 AI 岗位匹配分析使用。
--
-- 为什么只存文本、不存原始 PDF/DOCX：
--   1. 原件在用户自己的电脑/手机里，我们只需要文本
--   2. 存二进制要额外处理文件存储、清理、权限校验、格式预览——当前阶段不值得
--   3. 文本可以直接进提示词，是分析真正需要的东西
--
-- TEXT 上限 65535 字节 ≈ 2 万多个汉字，一份简历（3~10 KB）绰绰有余。

ALTER TABLE users
    ADD COLUMN profile_text TEXT NULL COMMENT '简历解析后的纯文本',
    ADD COLUMN profile_updated_at DATETIME NULL COMMENT '简历最后更新时间';
