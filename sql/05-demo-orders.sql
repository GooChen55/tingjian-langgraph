SET NAMES utf8mb4;
USE tingshu_order;
INSERT IGNORE INTO order_info(id,user_id,order_title,order_no,order_status,original_amount,order_amount,item_type,pay_way)
VALUES (900001,900001,'【演示】通勤听书专辑','LOCAL-DEMO-PAID-900001','0902',29.90,29.90,'1001','1103'),
       (900002,900001,'【演示】月度会员订单','LOCAL-DEMO-UNPAID-900002','0901',20.00,20.00,'1003','1103');
