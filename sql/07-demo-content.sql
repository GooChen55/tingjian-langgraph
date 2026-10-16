SET NAMES utf8mb4;
USE tingshu_album;
INSERT IGNORE INTO album_info(id,user_id,album_title,category3_id,album_intro,cover_url,include_track_count,pay_type,is_open,status)
VALUES(900001,900001,'【本地示例】音频播放与进度验证',1001,'使用课程资料提供的加肥猫和小毛驴音频，验证播放、暂停和进度恢复。','/listen/static/logo.png',2,'0101','1','0301');
UPDATE album_info SET category3_id=1001 WHERE id=900001 AND album_title='【本地示例】音频播放与进度验证';
INSERT IGNORE INTO track_info(id,user_id,album_id,track_title,order_num,cover_url,media_url,media_type,is_open,status)
VALUES(900001,'900001',900001,'【本地示例】加肥猫',1,'/listen/static/logo.png','/api/media/900001','mp3','1','0501'),
      (900002,'900001',900001,'【本地示例】小毛驴',2,'/listen/static/logo.png','/api/media/900002','mp3','1','0501');
