package com.atguigu.tingshu.listeningcontent;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
/** 本地内容入口复用专辑模块与课程库，不初始化云上传、机审和定时任务。 */
@SpringBootApplication(scanBasePackages={"com.atguigu.tingshu.listeningcontent","com.atguigu.tingshu.common"})
public class LocalContentApplication {
    public static void main(String[] args){SpringApplication.run(LocalContentApplication.class,args);}
}
