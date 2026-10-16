-- Define the permission before granting it; the role mapping has a foreign key.
INSERT IGNORE INTO tingshu_user.access_permission(code) VALUES ('content:manage');
INSERT IGNORE INTO tingshu_user.access_role_permission(role_code,permission_code)
VALUES ('administrator','content:manage');
