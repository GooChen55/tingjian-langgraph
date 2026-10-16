package com.atguigu.tingshu.common.config.redis;

import org.springframework.data.redis.serializer.StringRedisSerializer;
import org.springframework.data.redis.serializer.SerializationException;

/** Prefix logical keys at the serialization boundary, including Lua KEYS. */
public final class NamespacedKeySerializer extends StringRedisSerializer {
    private final String prefix;
    public NamespacedKeySerializer(String prefix) {
        if (!prefix.isEmpty() && !"aillisten:dev:".equals(prefix)) {
            throw new IllegalArgumentException("Unknown shared Redis resource scope");
        }
        this.prefix = prefix;
    }
    @Override public byte[] serialize(String key) {
        return key == null ? null : super.serialize(prefix + key);
    }
    @Override public String deserialize(byte[] bytes) {
        String key = super.deserialize(bytes);
        if (key == null) return null;
        if (!key.startsWith(prefix)) throw new SerializationException("Foreign Redis key");
        return key.substring(prefix.length());
    }
}
