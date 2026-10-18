-- Area 1: SQL that saves you work (Team Data Titans)
-- Four tables, two per version, identical in structure.
-- Only the column types (and where the id comes from) differ.
-- Developed against MariaDB 13.0.2.

CREATE DATABASE IF NOT EXISTS sql_features_project
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE sql_features_project;

-- ============================================================
-- MODERN version: native UUID and INET4
-- The server generates the ids (DEFAULT UUID()).
-- ============================================================

CREATE TABLE users_modern (
    id            UUID         NOT NULL DEFAULT UUID(),
    email         VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_modern_email (email)
) ENGINE=InnoDB;

CREATE TABLE login_log_modern (
    id           UUID      NOT NULL DEFAULT UUID(),
    user_id      UUID      NOT NULL,
    ip_address   INET4     NOT NULL,
    logged_in_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_login_log_modern_user (user_id),
    CONSTRAINT fk_login_log_modern_user
        FOREIGN KEY (user_id) REFERENCES users_modern (id)
) ENGINE=InnoDB;

-- ============================================================
-- BASELINE version: CHAR(36) and VARCHAR(15), the pre-feature way
-- ascii keeps the baseline fair: no wider default charset inflating it.
-- No DEFAULT UUID(): the application (Python) generates the id,
-- so it already knows the id and needs no read-back for it.
-- ============================================================

CREATE TABLE users_baseline (
    id            CHAR(36)     CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    email         VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_baseline_email (email)
) ENGINE=InnoDB;

CREATE TABLE login_log_baseline (
    id           CHAR(36)    CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    user_id      CHAR(36)    CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    ip_address   VARCHAR(15) CHARACTER SET ascii NOT NULL,
    logged_in_at TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_login_log_baseline_user (user_id),
    CONSTRAINT fk_login_log_baseline_user
        FOREIGN KEY (user_id) REFERENCES users_baseline (id)
) ENGINE=InnoDB;
