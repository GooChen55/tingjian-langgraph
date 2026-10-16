SET NAMES utf8mb4;
USE tingshu_user;
CREATE TABLE IF NOT EXISTS access_account (
 id bigint PRIMARY KEY AUTO_INCREMENT, username varchar(40) NOT NULL UNIQUE,
 user_id bigint NOT NULL UNIQUE, password_hash varchar(255) NOT NULL,
 enabled tinyint NOT NULL DEFAULT 1, create_time timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(user_id) REFERENCES user_info(id)
);
CREATE TABLE IF NOT EXISTS access_role (code varchar(40) PRIMARY KEY, label varchar(80) NOT NULL);
CREATE TABLE IF NOT EXISTS access_permission (code varchar(60) PRIMARY KEY);
CREATE TABLE IF NOT EXISTS access_role_permission (
 role_code varchar(40) NOT NULL, permission_code varchar(60) NOT NULL,
 PRIMARY KEY(role_code,permission_code), FOREIGN KEY(role_code) REFERENCES access_role(code),
 FOREIGN KEY(permission_code) REFERENCES access_permission(code)
);
CREATE TABLE IF NOT EXISTS access_user_role (
 user_id bigint NOT NULL, role_code varchar(40) NOT NULL,
 PRIMARY KEY(user_id,role_code), FOREIGN KEY(user_id) REFERENCES user_info(id),
 FOREIGN KEY(role_code) REFERENCES access_role(code)
);
INSERT IGNORE INTO access_role VALUES('administrator','管理员'),('reviewer','售后审核员');
INSERT IGNORE INTO access_permission VALUES('admin:access'),('after_sales:read'),('after_sales:review'),('operations:read');
INSERT IGNORE INTO access_role_permission VALUES
 ('administrator','admin:access'),('administrator','after_sales:read'),('administrator','after_sales:review'),('administrator','operations:read'),
 ('reviewer','admin:access'),('reviewer','after_sales:read'),('reviewer','after_sales:review');
INSERT IGNORE INTO access_permission VALUES('models:manage');
INSERT IGNORE INTO access_role_permission VALUES('administrator','models:manage');
