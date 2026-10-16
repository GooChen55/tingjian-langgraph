package com.atguigu.tingshu.user.api;

import com.atguigu.tingshu.common.util.MongoUtil;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.data.domain.Sort;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.index.Index;
import org.springframework.stereotype.Component;

/** Fail startup if the shared progress boundary cannot be enforced. */
@Component @Profile("vm")
public class ProgressIndexes implements ApplicationRunner {
    private final MongoTemplate mongo;
    public ProgressIndexes(MongoTemplate mongo){this.mongo=mongo;}
    @Override public void run(ApplicationArguments args){
        var indexes=mongo.indexOps(MongoUtil.LISTEN_PROGRESS_COLLECTION);
        indexes.ensureIndex(new Index().on("userId",Sort.Direction.ASC).on("trackId",Sort.Direction.ASC).unique().named("user_track_unique"));
        indexes.ensureIndex(new Index().on("userId",Sort.Direction.ASC).on("isShow",Sort.Direction.ASC).on("updateTime",Sort.Direction.DESC).named("recent_visible_progress"));
        indexes.ensureIndex(new Index().on("userId",Sort.Direction.ASC).on("updateTime",Sort.Direction.DESC).named("recent_progress"));
    }
}
