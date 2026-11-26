-- 岗位的「投递入口」链接，与现有的 url（岗位详情页）分开。
--
-- 为什么需要两个：
--   url        看 JD、核对岗位信息（Boss直聘岗位页、官网职位描述）
--   apply_url  真正提交简历的入口（OfferShow、官网招聘页、内推表单）
--
-- 现实情况：Boss直聘是"聊天投简历"模式，**没有公开的投递 URL**；
-- 而 OfferShow / 公司官网有真正的投递页。两者不能混在一个字段里，
-- 否则用户填了 OfferShow 的链接，就找不到 Boss 上的原始 JD 了。
--
-- 允许为 NULL：Boss 来源的岗位通常就是没有投递链接，需要在别处找。

ALTER TABLE jobs
    ADD COLUMN apply_url VARCHAR(500) NULL COMMENT '投递入口链接（可为空）';
