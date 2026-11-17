-- 004_create_users.sql
-- 日期: 2026-11-16
-- 目的: 用户表（Bearer token 存表方案，见 docs/ARCHITECTURE.md D5）
-- 影响: 新建表，不影响已有数据

CREATE TABLE IF NOT EXISTS users (
    id INT NOT NULL AUTO_INCREMENT,
    name VARCHAR(20) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    token VARCHAR(64) NULL,
    token_expires_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY `name` (`name`),
    UNIQUE KEY `token` (`token`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
