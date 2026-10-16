CREATE TABLE IF NOT EXISTS listening_ops.knowledge_document (
 id bigint PRIMARY KEY AUTO_INCREMENT,
 title varchar(120) NOT NULL,
 filename varchar(240) NOT NULL,
 desired_revision char(64) NOT NULL,
 active_revision char(64) NULL,
 object_key varchar(300) NOT NULL,
 active_path varchar(300) NULL,
 deleted tinyint NOT NULL DEFAULT 0,
 status varchar(24) NOT NULL DEFAULT 'QUEUED',
 error_code varchar(100) NULL,
 trace_json json NULL,
 actor_id bigint NOT NULL,
 created_at datetime(6) NOT NULL,
 updated_at datetime(6) NOT NULL,
 INDEX active_documents(deleted,status)
) ENGINE=InnoDB;
INSERT IGNORE INTO tingshu_user.access_permission(code) VALUES ('knowledge:manage');
INSERT IGNORE INTO tingshu_user.access_role_permission(role_code,permission_code)
VALUES ('administrator','knowledge:manage');
