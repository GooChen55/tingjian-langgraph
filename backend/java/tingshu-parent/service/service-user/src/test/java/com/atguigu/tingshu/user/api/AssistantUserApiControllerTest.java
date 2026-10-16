package com.atguigu.tingshu.user.api;

import com.atguigu.tingshu.common.util.AuthContextHolder;
import com.atguigu.tingshu.model.user.UserListenProcess;
import com.atguigu.tingshu.user.service.UserInfoService;
import com.atguigu.tingshu.vo.user.UserInfoVo;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.query.Query;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AssistantUserApiControllerTest {
    @AfterEach void cleanup() { AuthContextHolder.removeUserId(); }

    @Test void progressAlwaysUsesAuthenticatedUserAndBoundedQuery() {
        var users = mock(UserInfoService.class);
        var mongo = mock(MongoTemplate.class);
        AuthContextHolder.setUserId(42L);
        String collection=com.atguigu.tingshu.common.util.MongoUtil.getCollectionName(com.atguigu.tingshu.common.util.MongoUtil.MongoCollectionEnum.USER_LISTEN_PROCESS,42L);
        when(mongo.find(any(Query.class), eq(UserListenProcess.class), eq(collection)))
                .thenReturn(List.of());
        new AssistantUserApiController(users, mongo).progress();
        var captor = ArgumentCaptor.forClass(Query.class);
        verify(mongo).find(captor.capture(), eq(UserListenProcess.class), eq(collection));
        assertEquals(42L, captor.getValue().getQueryObject().get("userId"));
        assertEquals(10, captor.getValue().getLimit());
    }

    @Test void assistantProfileDoesNotExposeWechatIdentifier() {
        var users = mock(UserInfoService.class);
        var user = new UserInfoVo();
        user.setId(42L);
        user.setNickname("听友");
        user.setWxOpenId("private-open-id");
        AuthContextHolder.setUserId(42L);
        when(users.getUserInfoVo(42L)).thenReturn(user);
        var data = new AssistantUserApiController(users, mock(MongoTemplate.class)).me().getData();
        assertEquals(42L, data.get("id"));
        assertFalse(data.containsKey("wxOpenId"));
    }
}
