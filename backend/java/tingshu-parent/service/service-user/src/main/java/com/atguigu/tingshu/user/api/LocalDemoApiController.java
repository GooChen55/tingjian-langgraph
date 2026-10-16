package com.atguigu.tingshu.user.api;

import com.atguigu.tingshu.common.constant.RedisConstant;
import com.atguigu.tingshu.common.result.Result;
import com.atguigu.tingshu.model.user.UserListenProcess;
import com.atguigu.tingshu.user.service.UserInfoService;
import com.atguigu.tingshu.vo.user.UserInfoVo;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Profile;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.web.bind.annotation.*;
import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** 本地演示账号入口：必须启用开发环境 profile 和显式开关。 */
@Profile({"local","vm"})
@ConditionalOnProperty(name="listening.demo-login-enabled", havingValue="true")
@RestController
@RequestMapping("/api/user/local")
public class LocalDemoApiController {
    private final UserInfoService users;
    private final RedisTemplate<Object, Object> redis;
    private final MongoTemplate mongo;

    public LocalDemoApiController(UserInfoService users, RedisTemplate<Object, Object> redis, MongoTemplate mongo) {
        this.users = users;
        this.redis = redis;
        this.mongo = mongo;
    }

    @PostMapping("/login")
    public Result<Map<String, Object>> login() {
        UserInfoVo user = users.getUserInfoVo(900001L);
        if (user == null) throw new IllegalStateException("请先导入本地演示 SQL");
        String token = UUID.randomUUID().toString();
        redis.opsForValue().set(RedisConstant.USER_LOGIN_KEY_PREFIX + token, user, 1, TimeUnit.HOURS);
        String collection=com.atguigu.tingshu.common.util.MongoUtil.getCollectionName(
                com.atguigu.tingshu.common.util.MongoUtil.MongoCollectionEnum.USER_LISTEN_PROCESS,900001L);
        var query=org.springframework.data.mongodb.core.query.Query.query(
                org.springframework.data.mongodb.core.query.Criteria.where("userId").is(900001L).and("trackId").is(900001L));
        var initial=new org.springframework.data.mongodb.core.query.Update()
                .setOnInsert("_id",collection.equals("user_listen_progress")?"900001:900001":"local-demo-progress")
                .setOnInsert("userId",900001L).setOnInsert("albumId",900001L).setOnInsert("trackId",900001L)
                .setOnInsert("breakSecond",new BigDecimal("125")).setOnInsert("isShow",1)
                .setOnInsert("createTime",new Date()).setOnInsert("updateTime",new Date());
        try {mongo.upsert(query,initial,UserListenProcess.class,collection);}
        catch(org.springframework.dao.DuplicateKeyException concurrentSeed) { /* A concurrent login created the same seed. */ }
        return Result.ok(Map.of("token", token, "nickname", user.getNickname(), "demo", true));
    }
}
