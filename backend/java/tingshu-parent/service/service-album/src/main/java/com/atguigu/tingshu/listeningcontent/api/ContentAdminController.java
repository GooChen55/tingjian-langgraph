package com.atguigu.tingshu.listeningcontent.api;

import com.atguigu.tingshu.common.access.AccessService;
import com.atguigu.tingshu.common.result.Result;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** The business edit and its search event commit in one MySQL transaction. */
@RestController @Profile("vm") @RequestMapping("/api/admin/content")
public class ContentAdminController {
    private final JdbcTemplate db;
    private final AccessService access;
    public ContentAdminController(JdbcTemplate db,AccessService access){this.db=db;this.access=access;}
    public record Edit(@NotBlank @Size(min=2,max=200) String albumTitle,@NotNull Boolean published,
        @NotBlank @Pattern(regexp="^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$") String requestId){}
    @PatchMapping("/albums/{id}") @Transactional
    public Result<?> edit(@PathVariable long id,@Valid @RequestBody Edit edit,@RequestHeader(value="admin-token",required=false) String token){
        long actor=access.require(token,"content:manage");
        if(id<1)throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"专辑编号不正确");
        var rows=db.queryForList("SELECT id,status FROM album_info WHERE id=? AND is_deleted=0 FOR UPDATE",id);
        if(rows.isEmpty())throw new ResponseStatusException(HttpStatus.NOT_FOUND,"专辑不存在");
        String hash;
        try{hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest((id+"|"+actor+"|"+edit.albumTitle().trim()+"|"+edit.published()).getBytes(StandardCharsets.UTF_8)));}
        catch(Exception impossible){throw new IllegalStateException(impossible);}
        var previous=db.queryForList("SELECT request_hash FROM aillisten_dev_ops.search_outbox WHERE id=? FOR UPDATE",edit.requestId());
        if(!previous.isEmpty()){
            if(!hash.equals(previous.get(0).get("request_hash")))throw new ResponseStatusException(HttpStatus.CONFLICT,"请求编号已用于其他修改");
            return Result.ok(Map.of("requestId",edit.requestId(),"replayed",true));
        }
        if(edit.published()&&!"0301".equals(rows.get(0).get("status")))
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"专辑须通过审核后才能公开");
        db.update("UPDATE album_info SET album_title=?,is_open=?,update_time=CURRENT_TIMESTAMP WHERE id=?",edit.albumTitle().trim(),edit.published()?"1":"0",id);
        db.update("INSERT INTO aillisten_dev_ops.search_outbox(id,kind,aggregate_id,actor_id,request_hash,next_attempt,created_at,updated_at) VALUES(?,'ALBUM_CHANGED',?,?,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",edit.requestId(),id,actor,hash);
        return Result.ok(Map.of("requestId",edit.requestId(),"replayed",false));
    }
}
