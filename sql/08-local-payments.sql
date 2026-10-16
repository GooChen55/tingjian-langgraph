SET NAMES utf8mb4;
USE tingshu_order;
CREATE TABLE IF NOT EXISTS local_product (
 code varchar(40) PRIMARY KEY, title varchar(100) NOT NULL, amount decimal(10,2) NOT NULL, enabled tinyint NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO local_product VALUES('listening-demo','听见本地交易演示套餐（不解锁课程付费内容）',9.90,1);
CREATE TABLE IF NOT EXISTS local_checkout (
 order_id bigint PRIMARY KEY, user_id bigint NOT NULL, product_code varchar(40) NOT NULL,
 idempotency_key varchar(64) NOT NULL, expires_at datetime(6) NOT NULL,
 UNIQUE owner_key(user_id,idempotency_key), FOREIGN KEY(order_id) REFERENCES order_info(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS local_payment (
 id char(36) PRIMARY KEY, order_id bigint NOT NULL UNIQUE, amount decimal(10,2) NOT NULL,
 status varchar(20) NOT NULL, create_time datetime(6) NOT NULL, update_time datetime(6) NOT NULL,
 FOREIGN KEY(order_id) REFERENCES order_info(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS local_refund_job (
 id char(36) PRIMARY KEY, order_id bigint NOT NULL UNIQUE, payment_id char(36) NOT NULL UNIQUE,
 amount decimal(10,2) NOT NULL, status varchar(20) NOT NULL, scenario varchar(30) NOT NULL,
 attempts int NOT NULL DEFAULT 0, available_at datetime(6) NOT NULL, actor_id bigint NOT NULL,
 last_error varchar(100) NULL, create_time datetime(6) NOT NULL, update_time datetime(6) NOT NULL,
 INDEX dispatch(status,available_at), FOREIGN KEY(id) REFERENCES after_sales_request(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS local_provider_receipt (
 refund_id char(36) PRIMARY KEY, receipt_id char(36) NOT NULL UNIQUE, amount decimal(10,2) NOT NULL,
 create_time datetime(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS local_callback (
 receipt_id varchar(64) PRIMARY KEY, kind varchar(10) NOT NULL, target_id char(36) NOT NULL,
 amount decimal(10,2) NOT NULL, outcome varchar(10) NOT NULL, create_time datetime(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS local_transaction_event (
 id bigint PRIMARY KEY AUTO_INCREMENT, order_id bigint NOT NULL, event_type varchar(30) NOT NULL,
 actor_id bigint NULL, create_time datetime(6) NOT NULL, INDEX order_events(order_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
USE tingshu_user;
INSERT IGNORE INTO access_permission VALUES('payments:manage');
INSERT IGNORE INTO access_role_permission VALUES('administrator','payments:manage');
