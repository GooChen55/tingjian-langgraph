package com.atguigu.tingshu.common.access;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;

/** 管理会话独立于听友 token；每次授权查询当前数据库角色，撤销权限即时生效。 */
@Service
public class AccessService {
    @org.springframework.beans.factory.annotation.Value("${listening.user-schema:tingshu_user}")
    private String userSchema = "tingshu_user";
    private String table(String name) {
        if (!Set.of("tingshu_user", "aillisten_dev_user").contains(userSchema)) throw new IllegalArgumentException("Unknown user schema");
        return "`" + userSchema + "`.`" + name + "`";
    }
    private final JdbcTemplate db;
    private final StringRedisTemplate redis;
    private final String dummyHash = Passwords.hash("dummy-password-no-account");
    public AccessService(JdbcTemplate db, StringRedisTemplate redis) { this.db=db; this.redis=redis; }
    public Set<String> permissions(long user) {
        return new LinkedHashSet<>(db.queryForList("SELECT DISTINCT rp.permission_code FROM "+table("access_user_role")+" ur JOIN "+table("access_role_permission")+" rp ON rp.role_code=ur.role_code JOIN "+table("access_account")+" a ON a.user_id=ur.user_id JOIN "+table("user_info")+" u ON u.id=a.user_id WHERE ur.user_id=? AND a.enabled=1 AND u.is_deleted=0", String.class, user));
    }
    public List<String> roles(long user) {
        return db.queryForList("SELECT role_code FROM "+table("access_user_role")+" WHERE user_id=?", String.class, user);
    }
    public long authenticate(String username, String password, String remote) {
        String attemptKey = "listening:login-attempt:" + digest(remote + ":" + username);
        Long attempts = redis.opsForValue().increment(attemptKey);
        if (attempts != null && attempts == 1) redis.expire(attemptKey, 5, TimeUnit.MINUTES);
        if (attempts != null && attempts > 10) throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS,"尝试过多，请 5 分钟后重试");
        var rows = db.queryForList("SELECT a.user_id,a.password_hash,a.enabled FROM "+table("access_account")+" a JOIN "+table("user_info")+" u ON u.id=a.user_id WHERE a.username=? AND u.is_deleted=0",username);
        boolean valid = Passwords.matches(password, rows.isEmpty() ? dummyHash : (String)rows.get(0).get("password_hash"));
        if (!valid || rows.isEmpty() || ((Number)rows.get(0).get("enabled")).intValue()!=1)
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,"账号或密码不正确");
        redis.delete(attemptKey);
        return ((Number)rows.get(0).get("user_id")).longValue();
    }
    public String adminLogin(long user) {
        if (!permissions(user).contains("admin:access")) throw new ResponseStatusException(HttpStatus.FORBIDDEN,"没有管理端权限");
        String token=UUID.randomUUID().toString()+UUID.randomUUID();
        redis.opsForValue().set(adminKey(token),Long.toString(user),30,TimeUnit.MINUTES);
        return token;
    }
    public long require(String token, String permission) {
        if (token==null || token.length()>128 || token.length()<32) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,"请登录管理端");
        String value=redis.opsForValue().get(adminKey(token));
        if (value==null) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,"管理登录已过期");
        long user=Long.parseLong(value);
        Set<String> current=permissions(user);
        if (!current.contains("admin:access") || !current.contains(permission)) throw new ResponseStatusException(HttpStatus.FORBIDDEN,"没有此操作权限");
        return user;
    }
    public void logout(String token) { if(token!=null) redis.delete(adminKey(token)); }
    private static String adminKey(String token) { return "listening:admin:"+digest(token); }
    private static String digest(String value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))); }
        catch(Exception error) { throw new IllegalStateException(error); }
    }
}
