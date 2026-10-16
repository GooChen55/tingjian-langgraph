package com.atguigu.tingshu.common.util;

import lombok.Getter;

public class MongoUtil {
    public static final String LISTEN_PROGRESS_COLLECTION = "user_listen_progress";

    public static String progressCollection(Long userId, boolean unified) {
        if (userId == null || userId < 1) throw new IllegalArgumentException("Authenticated user required");
        return unified ? LISTEN_PROGRESS_COLLECTION : "userListenProcess_" + userId;
    }

    @Getter
    public enum MongoCollectionEnum {

        USER_SUBSCRIBE(100,"userSubscribe"),
        USER_COLLECT(100,"userCollect"),
        USER_LISTEN_PROCESS(100,"userListenProcess"),
        COMMENT(100,"comment"),
        COMMENT_PRAISE(100,"commentPraise"),
        ;

        private Integer partition;
        private String collectionPrefix;

        MongoCollectionEnum(Integer partition, String collectionPrefix) {
            this.partition = partition;
            this.collectionPrefix = collectionPrefix;
        }

    }


    /**
     * 获取mongo表名
     * @param mongoCollection Collection前缀
     * @param userId 用户ID
     * @return
     */
    public static String getCollectionName(MongoCollectionEnum mongoCollection, Long userId) {
        if (mongoCollection == MongoCollectionEnum.USER_LISTEN_PROCESS) {
            return progressCollection(userId, "vm".equals(System.getenv("LISTENING_INFRASTRUCTURE")));
        }
        return mongoCollection.getCollectionPrefix() + "_" + userId;
    }
}

