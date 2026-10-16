package com.atguigu.tingshu.user.api;

import com.atguigu.tingshu.common.login.GuiGuLogin;
import com.atguigu.tingshu.common.result.Result;
import com.atguigu.tingshu.common.util.AuthContextHolder;
import com.atguigu.tingshu.common.util.MongoUtil;
import com.atguigu.tingshu.model.user.UserListenProcess;
import com.atguigu.tingshu.user.service.UserInfoService;
import org.springframework.data.domain.Sort;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.query.Criteria;
import org.springframework.data.mongodb.core.query.Query;
import org.springframework.web.bind.annotation.*;
import java.util.*;

/** AI 只访问当前登录用户，接口不接收 userId。 */
@RestController
@RequestMapping("/api/user/assistant")
public class AssistantUserApiController {
    private final UserInfoService users;
    private final MongoTemplate mongo;

    public AssistantUserApiController(UserInfoService users, MongoTemplate mongo) {
        this.users = users;
        this.mongo = mongo;
    }

    @GuiGuLogin
    @GetMapping("/me")
    public Result<Map<String, Object>> me() {
        var user = users.getUserInfoVo(AuthContextHolder.getUserId());
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("id", user.getId());
        data.put("nickname", user.getNickname());
        data.put("isVip", user.getIsVip());
        data.put("vipExpireTime", user.getVipExpireTime());
        return Result.ok(data);
    }

    @GuiGuLogin
    @GetMapping("/progress")
    public Result<List<UserListenProcess>> progress() {
        Long userId = AuthContextHolder.getUserId();
        Query query = Query.query(Criteria.where("userId").is(userId)
                .and("isShow").is(1)).with(Sort.by(Sort.Direction.DESC, "updateTime")).limit(10);
        return Result.ok(mongo.find(query, UserListenProcess.class,
                MongoUtil.getCollectionName(MongoUtil.MongoCollectionEnum.USER_LISTEN_PROCESS, userId)));
    }
}
