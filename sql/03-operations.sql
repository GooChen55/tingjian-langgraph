SET NAMES utf8mb4;
CREATE DATABASE IF NOT EXISTS listening_ops CHARACTER SET utf8mb4;
CREATE OR REPLACE SQL SECURITY DEFINER VIEW listening_ops.v_content_summary AS
SELECT (SELECT COUNT(*) FROM tingshu_album.album_info WHERE is_deleted=0 AND id<>900001) AS album_count,
       (SELECT COUNT(*) FROM tingshu_album.track_info WHERE is_deleted=0 AND id NOT IN(900001,900002)) AS track_count;
CREATE OR REPLACE SQL SECURITY DEFINER VIEW listening_ops.v_category_content AS
SELECT COALESCE(c.name,'未分类') AS category_name, COUNT(DISTINCT a.id) AS album_count,
       COUNT(t.id) AS track_count
FROM tingshu_album.album_info a
LEFT JOIN tingshu_album.base_category3 c ON c.id=a.category3_id AND c.is_deleted=0
LEFT JOIN tingshu_album.track_info t ON t.album_id=a.id AND t.is_deleted=0
WHERE a.is_deleted=0 AND a.id<>900001 GROUP BY COALESCE(c.name,'未分类');
CREATE OR REPLACE SQL SECURITY DEFINER VIEW listening_ops.v_user_summary AS
SELECT COUNT(*) AS user_count,
       COALESCE(SUM(is_vip=1 AND vip_expire_time>CURRENT_DATE()),0) AS active_vip_count
FROM tingshu_user.user_info WHERE is_deleted=0 AND wx_open_id NOT LIKE 'local-demo-%';
CREATE OR REPLACE SQL SECURITY DEFINER VIEW listening_ops.v_user_daily AS
SELECT DATE(create_time) AS day, COUNT(*) AS new_user_count
FROM tingshu_user.user_info WHERE is_deleted=0 AND wx_open_id NOT LIKE 'local-demo-%'
GROUP BY DATE(create_time);
CREATE OR REPLACE SQL SECURITY DEFINER VIEW listening_ops.v_order_summary AS
SELECT COUNT(*) AS order_count, COALESCE(SUM(order_status='0902'),0) AS paid_order_count,
       COALESCE(SUM(CASE WHEN order_status='0902' THEN order_amount ELSE 0 END),0) AS paid_order_amount
FROM tingshu_order.order_info WHERE is_deleted=0 AND user_id NOT IN (900001) AND order_no NOT LIKE 'LOCAL-TEST-%';
CREATE OR REPLACE SQL SECURITY DEFINER VIEW listening_ops.v_order_daily AS
SELECT DATE(create_time) AS day, COUNT(*) AS order_count,
       SUM(order_status='0902') AS paid_order_count,
       SUM(CASE WHEN order_status='0902' THEN order_amount ELSE 0 END) AS paid_order_amount
FROM tingshu_order.order_info WHERE is_deleted=0 AND user_id NOT IN (900001) AND order_no NOT LIKE 'LOCAL-TEST-%'
GROUP BY DATE(create_time);
CREATE USER IF NOT EXISTS 'listening_reader'@'%' IDENTIFIED BY '__READER_PASSWORD__';
ALTER USER 'listening_reader'@'%' IDENTIFIED BY '__READER_PASSWORD__';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'listening_reader'@'%';
GRANT SELECT ON listening_ops.v_content_summary TO 'listening_reader'@'%';
GRANT SELECT ON listening_ops.v_category_content TO 'listening_reader'@'%';
GRANT SELECT ON listening_ops.v_user_summary TO 'listening_reader'@'%';
GRANT SELECT ON listening_ops.v_user_daily TO 'listening_reader'@'%';
GRANT SELECT ON listening_ops.v_order_summary TO 'listening_reader'@'%';
GRANT SELECT ON listening_ops.v_order_daily TO 'listening_reader'@'%';
