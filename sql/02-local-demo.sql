SET NAMES utf8mb4;
USE tingshu_user;
INSERT IGNORE INTO user_info(id, nickname, wx_open_id, is_vip, vip_expire_time, status, create_time, update_time, is_deleted)
VALUES(900001, '本地演示听友', 'local-demo-900001', 1, '2027-01-01 00:00:00', '1', NOW(), NOW(), 0);
