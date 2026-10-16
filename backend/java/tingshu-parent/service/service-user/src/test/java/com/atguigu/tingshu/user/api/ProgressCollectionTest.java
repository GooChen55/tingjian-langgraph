package com.atguigu.tingshu.user.api;

import com.atguigu.tingshu.common.util.MongoUtil;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ProgressCollectionTest {
    @Test void unifiedCollectionDoesNotGrowWithAccountCount(){
        assertEquals("user_listen_progress",MongoUtil.progressCollection(42L,true));
        assertEquals(MongoUtil.progressCollection(42L,true),MongoUtil.progressCollection(43L,true));
        assertEquals("userListenProcess_42",MongoUtil.progressCollection(42L,false));
    }
    @Test void anonymousUsersCannotGetAProgressCollection(){
        assertThrows(IllegalArgumentException.class,()->MongoUtil.progressCollection(null,true));
        assertThrows(IllegalArgumentException.class,()->MongoUtil.progressCollection(0L,true));
    }
}
