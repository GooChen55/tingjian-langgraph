SET NAMES utf8mb4;
USE tingshu_order;
CREATE TABLE IF NOT EXISTS after_sales_request (
 id char(36) PRIMARY KEY,
 user_id bigint NOT NULL,
 order_id bigint NOT NULL,
 order_no varchar(50) NOT NULL,
 order_title varchar(100) NOT NULL,
 amount decimal(10,2) NOT NULL,
 reason varchar(300) NOT NULL,
 status varchar(20) NOT NULL,
 expires_at datetime(6) NOT NULL,
 submitted_at datetime(6) NULL,
 create_time datetime(6) NOT NULL,
 update_time datetime(6) NOT NULL,
 INDEX owner_recent(user_id,create_time),
 INDEX owner_order_state(user_id,order_id,status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS after_sales_event (
 id bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,
 request_id char(36) NOT NULL,
 user_id bigint NOT NULL,
 event_type varchar(20) NOT NULL,
 create_time datetime(6) NOT NULL,
 INDEX request_events(request_id,id),
 FOREIGN KEY(request_id) REFERENCES after_sales_request(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
