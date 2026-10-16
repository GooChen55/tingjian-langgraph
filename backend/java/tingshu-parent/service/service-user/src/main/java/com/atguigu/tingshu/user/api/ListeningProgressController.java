package com.atguigu.tingshu.user.api;
import com.atguigu.tingshu.common.login.GuiGuLogin;
import com.atguigu.tingshu.common.result.Result;
import com.atguigu.tingshu.common.util.AuthContextHolder;
import com.atguigu.tingshu.common.util.MongoUtil;
import com.atguigu.tingshu.model.user.UserListenProcess;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.query.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.math.BigDecimal;
import java.util.Date;
import java.util.Map;

@RestController @RequestMapping("/api/user/listening/progress")
public class ListeningProgressController {
 @org.springframework.beans.factory.annotation.Value("${listening.album-schema:tingshu_album}")
 private String albumSchema = "tingshu_album";
 @jakarta.annotation.PostConstruct private void validateSchema(){
  if(!java.util.Set.of("tingshu_album","aillisten_dev_album").contains(albumSchema))throw new IllegalArgumentException("Unknown album schema");
 }
 private final MongoTemplate mongo;private final JdbcTemplate db;
 public ListeningProgressController(MongoTemplate mongo,JdbcTemplate db){this.mongo=mongo;this.db=db;}
 public record Progress(@NotNull @Positive Long albumId,@NotNull @Positive Long trackId,
                        @NotNull @DecimalMin("0") @DecimalMax("86400") BigDecimal breakSecond){}
 private Query query(long owner,long track){return Query.query(Criteria.where("userId").is(owner).and("trackId").is(track));}
 private String collection(long owner){return MongoUtil.getCollectionName(MongoUtil.MongoCollectionEnum.USER_LISTEN_PROCESS,owner);}
 @GetMapping("/{track}") @GuiGuLogin public Result<?> read(@PathVariable long track){
  long owner=AuthContextHolder.getUserId();var record=mongo.findOne(query(owner,track),UserListenProcess.class,collection(owner));
  return Result.ok(Map.of("breakSecond",record==null?BigDecimal.ZERO:record.getBreakSecond()));
 }
 @PostMapping @GuiGuLogin public Result<?> save(@Valid @RequestBody Progress progress){
  var rows=db.queryForList("SELECT t.media_duration,t.order_num,a.pay_type,a.tracks_for_free FROM `"+albumSchema+"`.track_info t JOIN `"+albumSchema+"`.album_info a ON a.id=t.album_id WHERE t.id=? AND a.id=? AND t.is_deleted=0 AND a.is_deleted=0 AND t.is_open='1' AND a.is_open='1' AND t.status='0501' AND a.status='0301'",progress.trackId,progress.albumId);
  if(rows.isEmpty())throw new ResponseStatusException(HttpStatus.NOT_FOUND,"声音与专辑不匹配或未公开");
  var row=rows.get(0);
  if(!"0101".equals(row.get("pay_type"))&&((Number)row.get("order_num")).intValue()>((Number)row.get("tracks_for_free")).intValue())
   throw new ResponseStatusException(HttpStatus.FORBIDDEN,"付费播放尚未接入");
  BigDecimal duration=(BigDecimal)row.get("media_duration");
  if(duration.signum()>0&&progress.breakSecond.compareTo(duration)>0)throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"进度不能超过声音时长");
  long owner=AuthContextHolder.getUserId();var now=new Date();
  var update=new Update().set("albumId",progress.albumId).set("breakSecond",progress.breakSecond).set("isShow",1).set("updateTime",now)
   .setOnInsert("_id",owner+":"+progress.trackId).setOnInsert("userId",owner).setOnInsert("trackId",progress.trackId).setOnInsert("createTime",now);
  try {mongo.upsert(query(owner,progress.trackId),update,UserListenProcess.class,collection(owner));}
  catch(org.springframework.dao.DuplicateKeyException race){mongo.updateFirst(query(owner,progress.trackId),update,UserListenProcess.class,collection(owner));}
  return Result.ok(Map.of("saved",true,"breakSecond",progress.breakSecond));
 }
}
