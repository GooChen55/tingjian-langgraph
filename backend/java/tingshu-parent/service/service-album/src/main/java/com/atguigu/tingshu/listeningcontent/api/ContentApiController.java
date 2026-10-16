package com.atguigu.tingshu.listeningcontent.api;

import com.atguigu.tingshu.common.result.Result;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.util.*;

@RestController @RequestMapping("/api/content")
public class ContentApiController {
    private final JdbcTemplate db;
    public ContentApiController(JdbcTemplate db){this.db=db;}
    private Map<String,Object> camel(Map<String,Object> row){
        var result=new LinkedHashMap<String,Object>();
        row.forEach((key,value)->{var parts=key.split("_");String name=parts[0];for(int i=1;i<parts.length;i++) name+=Character.toUpperCase(parts[i].charAt(0))+parts[i].substring(1);result.put(name,value);});return result;
    }
    private static final String PUBLIC=" is_deleted=0 AND is_open='1' AND status='0301' ";
    @GetMapping("/categories") public Result<?> categories(){
        var tree=new LinkedHashMap<Long,Map<String,Object>>();
        var seconds=new LinkedHashMap<Long,Map<String,Object>>();
        for(var raw:db.queryForList("SELECT category1_id,category1_name,category2_id,category2_name,category3_id,category3_name FROM base_category_view ORDER BY category1_id,category2_id,category3_id")){
            long first=((Number)raw.get("category1_id")).longValue(),second=((Number)raw.get("category2_id")).longValue();
            var root=tree.computeIfAbsent(first,id->new LinkedHashMap<>(Map.of("categoryId",id,"categoryName",raw.get("category1_name"),"categoryChild",new ArrayList<>())));
            if(!seconds.containsKey(second)){var item=new LinkedHashMap<String,Object>(Map.of("categoryId",second,"categoryName",raw.get("category2_name"),"categoryChild",new ArrayList<>()));seconds.put(second,item);((List)root.get("categoryChild")).add(item);}
            ((List)seconds.get(second).get("categoryChild")).add(Map.of("categoryId",raw.get("category3_id"),"categoryName",raw.get("category3_name"),"categoryChild",List.of()));
        }
        return Result.ok(new ArrayList<>(tree.values()));
    }
    @GetMapping("/channel/{category}") public Result<?> channel(@PathVariable long category){
        var groups=new ArrayList<Map<String,Object>>();
        for(var c:db.queryForList("SELECT DISTINCT category3_id,category3_name FROM base_category_view WHERE category1_id=? ORDER BY category3_id LIMIT 4",category)){
            var rows=db.queryForList("SELECT a.id,a.album_title,a.cover_url,a.pay_type,v.category1_id,v.category2_id,a.category3_id,COALESCE((SELECT SUM(s.stat_num) FROM album_stat s WHERE s.album_id=a.id AND s.stat_type='0401' AND s.is_deleted=0),0) AS play_stat_num FROM album_info a JOIN base_category_view v ON v.category3_id=a.category3_id WHERE a.is_deleted=0 AND a.is_open='1' AND a.status='0301' AND a.category3_id=? ORDER BY (a.id=900001) DESC,a.id LIMIT 6",c.get("category3_id"));
            if(!rows.isEmpty())groups.add(Map.of("baseCategory3",Map.of("id",c.get("category3_id"),"name",c.get("category3_name")),"list",rows.stream().map(this::camel).toList()));
        }return Result.ok(groups);
    }
    @GetMapping("/top/{category}") public Result<?> top(@PathVariable long category){
        return Result.ok(db.queryForList("SELECT category3_id AS id,category3_name AS name FROM base_category_view WHERE category1_id=? LIMIT 8",category));
    }
    @GetMapping("/albums") public Result<?> albums(@RequestParam(defaultValue="") String q,@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="12") int size,@RequestParam(required=false) Long category3){
        if(q.length()>100||page<1||page>10000||size<1||size>50) throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"查询参数不正确");
        String where=PUBLIC+" AND album_title LIKE ? ";var args=new ArrayList<Object>();args.add("%"+q+"%");
        if(category3!=null){if(category3<1)throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"分类参数不正确");where+=" AND category3_id=?";args.add(category3);}
        long total=db.queryForObject("SELECT COUNT(*) FROM album_info WHERE "+where,Long.class,args.toArray());args.add(size);args.add((page-1)*size);
        var rows=db.queryForList("SELECT id,album_title,album_intro,cover_url,pay_type,include_track_count FROM album_info WHERE "+where+" ORDER BY (id=900001) DESC,id LIMIT ? OFFSET ?",args.toArray());
        return Result.ok(Map.of("records",rows.stream().map(this::camel).toList(),"total",total,"page",page,"size",size));
    }
    /** Hydrate search candidates from current business visibility, never ES alone. */
    @GetMapping("/albums/search-results") public Result<?> searchResults(@RequestParam List<Long> ids){
        if(ids.isEmpty()||ids.size()>50||ids.stream().anyMatch(id->id==null||id<1))
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"搜索候选不合法");
        String placeholders=String.join(",",Collections.nCopies(ids.size(),"?"));
        var rows=db.queryForList("SELECT id,album_title,album_intro,cover_url,pay_type,include_track_count FROM album_info WHERE "+PUBLIC+" AND id IN ("+placeholders+")",ids.toArray());
        rows.sort(Comparator.comparingInt(row->ids.indexOf(((Number)row.get("id")).longValue())));
        return Result.ok(rows.stream().map(this::camel).toList());
    }
    private Map<String,Object> album(long id){
        var rows=db.queryForList("SELECT id,album_title,album_intro,cover_url,pay_type,category3_id,include_track_count,tracks_for_free FROM album_info WHERE id=? AND "+PUBLIC,id);
        if(rows.isEmpty())throw new ResponseStatusException(HttpStatus.NOT_FOUND,"专辑不存在或未公开");return camel(rows.get(0));
    }
    @GetMapping("/albums/{id}") public Result<?> details(@PathVariable long id){
        var info=album(id);return Result.ok(info);
    }
    @GetMapping("/albums/{id}/tracks") public Result<?> tracks(@PathVariable long id,@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="20") int size){
        var info=album(id);if(page<1||page>10000||size<1||size>50)throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"分页参数不正确");
        String where=" album_id=? AND is_deleted=0 AND is_open='1' AND status='0501' ";
        var rows=db.queryForList("SELECT id,album_id,track_title,order_num,media_duration,cover_url FROM track_info WHERE "+where+" ORDER BY order_num,id LIMIT ? OFFSET ?",id,size,(page-1)*size);
        var records=rows.stream().map(this::camel).toList();records.forEach(r->r.put("playable",canPlay(info,((Number)r.get("orderNum")).intValue())));
        return Result.ok(Map.of("records",records,"total",db.queryForObject("SELECT COUNT(*) FROM track_info WHERE "+where,Long.class,id),"page",page,"size",size));
    }
    private boolean canPlay(Map<String,Object> info,int number){return "0101".equals(info.get("payType"))||number<=((Number)info.get("tracksForFree")).intValue();}
    @GetMapping("/tracks/{id}") public Result<?> track(@PathVariable long id){
        var rows=db.queryForList("SELECT id,album_id,track_title,order_num,media_url,media_duration,cover_url FROM track_info WHERE id=? AND is_deleted=0 AND is_open='1' AND status='0501'",id);
        if(rows.isEmpty())throw new ResponseStatusException(HttpStatus.NOT_FOUND,"声音不存在或未公开");
        var result=camel(rows.get(0));var info=album(((Number)result.get("albumId")).longValue());
        if(!canPlay(info,((Number)result.get("orderNum")).intValue()))throw new ResponseStatusException(HttpStatus.FORBIDDEN,"当前仅接通免费内容与免费试听；付费播放尚未接入");
        return Result.ok(result);
    }
}
