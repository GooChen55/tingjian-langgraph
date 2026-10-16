package com.atguigu.tingshu.user.api;

import com.atguigu.tingshu.common.access.AccessService;
import com.atguigu.tingshu.common.access.Passwords;
import com.atguigu.tingshu.common.constant.RedisConstant;
import com.atguigu.tingshu.common.login.GuiGuLogin;
import com.atguigu.tingshu.common.result.Result;
import com.atguigu.tingshu.common.util.AuthContextHolder;
import com.atguigu.tingshu.user.service.UserInfoService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.sql.Statement;
import java.util.*;
import java.util.concurrent.TimeUnit;

@RestController @RequestMapping("/api/access")
public class AccessApiController {
    private final AccessService access;
    private final JdbcTemplate db;
    private final UserInfoService users;
    private final RedisTemplate<Object,Object> redis;
    public AccessApiController(AccessService access,JdbcTemplate db,UserInfoService users,RedisTemplate<Object,Object> redis) {
        this.access=access;this.db=db;this.users=users;this.redis=redis;
    }
    public record Credentials(@NotBlank @Pattern(regexp="^[a-zA-Z0-9_]{4,40}$") String username,
                              @NotBlank @Size(min=10,max=128) String password) {}
    @PostMapping("/register") @Transactional
    public Result<?> register(@Valid @RequestBody Credentials req) {
        if(!db.queryForList("SELECT id FROM access_account WHERE username=?",req.username).isEmpty())
            throw new ResponseStatusException(HttpStatus.CONFLICT,"账号名已存在");
        var key=new GeneratedKeyHolder();
        db.update(connection -> {
            var statement=connection.prepareStatement("INSERT INTO user_info(wx_open_id,nickname,avatar_url,status) VALUES(?,?,?,'1')",Statement.RETURN_GENERATED_KEYS);
            statement.setString(1,"account-"+UUID.randomUUID());statement.setString(2,req.username);statement.setString(3,"/static/avatar.jpg");return statement;
        },key);
        long user=Objects.requireNonNull(key.getKey()).longValue();
        db.update("INSERT INTO access_account(username,user_id,password_hash) VALUES(?,?,?)",req.username,user,Passwords.hash(req.password));
        return Result.ok(Map.of("registered",true,"username",req.username));
    }
    @PostMapping("/login")
    public Result<?> login(@Valid @RequestBody Credentials req,HttpServletRequest request) {
        long user=access.authenticate(req.username,req.password,request.getRemoteAddr());
        String token=UUID.randomUUID().toString();
        redis.opsForValue().set(RedisConstant.USER_LOGIN_KEY_PREFIX+token,users.getUserInfoVo(user),1,TimeUnit.HOURS);
        return Result.ok(Map.of("token",token,"username",req.username));
    }
    @PostMapping("/logout") @GuiGuLogin
    public Result<?> logout(@RequestHeader("token") String token) { redis.delete(RedisConstant.USER_LOGIN_KEY_PREFIX+token);return Result.ok(); }
    @GetMapping("/permissions") @GuiGuLogin
    public Result<?> permissions() { return Result.ok(Map.of("permissions",access.permissions(AuthContextHolder.getUserId()))); }
    @PostMapping("/admin/login")
    public Result<?> adminLogin(@Valid @RequestBody Credentials req,HttpServletRequest request) {
        long user=access.authenticate(req.username,req.password,request.getRemoteAddr());
        return Result.ok(Map.of("token",access.adminLogin(user),"expiresIn",1800));
    }
    @GetMapping("/admin/me")
    public Result<?> adminMe(@RequestHeader(value="admin-token",required=false) String token) {
        long user=access.require(token,"admin:access");
        return Result.ok(Map.of("id",Long.toString(user),"roles",access.roles(user),"permissions",access.permissions(user)));
    }
    @PostMapping("/admin/logout")
    public Result<?> adminLogout(@RequestHeader(value="admin-token",required=false) String token) { access.logout(token);return Result.ok(); }
}
