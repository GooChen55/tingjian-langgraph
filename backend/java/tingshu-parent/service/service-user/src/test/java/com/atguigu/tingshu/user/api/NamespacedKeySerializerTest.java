package com.atguigu.tingshu.user.api;

import com.atguigu.tingshu.common.config.redis.NamespacedKeySerializer;
import org.junit.jupiter.api.Test;
import java.nio.charset.StandardCharsets;
import static org.junit.jupiter.api.Assertions.*;

class NamespacedKeySerializerTest {
    @Test void prefixesBothSessionAndOpaqueCallbackKeys() {
        var serializer = new NamespacedKeySerializer("aillisten:dev:");
        for (String key : new String[]{"user:login:token", "opaque-correlation-id"}) {
            byte[] encoded = serializer.serialize(key);
            assertEquals("aillisten:dev:" + key, new String(encoded, StandardCharsets.UTF_8));
            assertEquals(key, serializer.deserialize(encoded));
        }
        assertThrows(RuntimeException.class, () -> serializer.deserialize("user:login:foreign".getBytes(StandardCharsets.UTF_8)));
        assertThrows(IllegalArgumentException.class, () -> new NamespacedKeySerializer("other-project:"));
    }
    @Test void localProfileKeepsExistingSessionsCompatible() {
        var serializer = new NamespacedKeySerializer("");
        assertEquals("user:login:token", new String(serializer.serialize("user:login:token"), StandardCharsets.UTF_8));
        assertNull(serializer.serialize(null));
        assertNull(serializer.deserialize(null));
    }
}
