package com.atguigu.tingshu.order.service;

import org.springframework.beans.factory.annotation.*;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;

/** Isolated local channel: no real money, no course paid-content entitlement. */
@Service @Profile({"local","vm"})
public class LocalPaymentService {
    private final JdbcTemplate db; private final Clock clock; private final String secret;
    @Autowired public LocalPaymentService(JdbcTemplate db,@Value("${LISTENING_PAYMENT_CALLBACK_SECRET:}") String secret){this(db,Clock.systemUTC(),secret);}
    LocalPaymentService(JdbcTemplate db,Clock clock,String secret){this.db=db;this.clock=clock;this.secret=secret;}
    public record Callback(String kind,String targetId,String receiptId,String amount,String outcome,long timestamp){}
    private ResponseStatusException error(int status,String message){return new ResponseStatusException(HttpStatus.valueOf(status),message);}
    private Timestamp now(){return Timestamp.from(clock.instant().truncatedTo(java.time.temporal.ChronoUnit.MICROS));}
    private Instant instant(Object value){
        if(value instanceof Timestamp t)return t.toInstant();
        if(value instanceof LocalDateTime t)return t.atZone(ZoneId.of("Asia/Shanghai")).toInstant();
        throw new IllegalStateException("Unsupported database datetime type");
    }
    private Map<String,Object> one(String sql,Object...args){var rows=db.queryForList(sql,args);if(rows.isEmpty())throw error(404,"本地交易记录不存在");return rows.get(0);}
    private long number(Map<String,Object> row,String key){return ((Number)row.get(key)).longValue();}
    private BigDecimal amount(Map<String,Object> row){return (BigDecimal)row.get("amount");}
    private void event(long order,String type,Long actor){db.update("INSERT INTO local_transaction_event(order_id,event_type,actor_id,create_time) VALUES(?,?,?,?)",order,type,actor,now());}
    private Map<String,Object> owned(long owner,long order,boolean lock){return one("SELECT o.*,c.expires_at FROM order_info o JOIN local_checkout c ON c.order_id=o.id WHERE o.id=? AND o.user_id=? AND o.is_deleted=0"+(lock?" FOR UPDATE":""),order,owner);}
    private boolean expired(Map<String,Object> order){return !instant(order.get("expires_at")).isAfter(clock.instant());}
    private void close(long id,String type,Long actor){
        if(db.update("UPDATE order_info SET order_status='0903' WHERE id=? AND order_status='0901'",id)>0){
            db.update("UPDATE local_payment SET status='CLOSED',update_time=? WHERE order_id=? AND status<>'SUCCEEDED'",now(),id);event(id,type,actor);
        }
    }
    public List<Map<String,Object>> products(){return db.queryForList("SELECT code,title,amount,'LOCAL_SIMULATOR' AS channel FROM local_product WHERE enabled=1 ORDER BY code");}
    @Transactional public Map<String,Object> checkout(long owner,String product,String key){
        if(key==null||!key.matches("[a-zA-Z0-9_-]{16,64}"))throw error(422,"下单需要 16 至 64 位幂等键");
        // One local catalog product; locking it also serializes price changes and repeated submissions.
        var p=one("SELECT * FROM local_product WHERE code=? AND enabled=1 FOR UPDATE",product);
        var old=db.queryForList("SELECT * FROM local_checkout WHERE user_id=? AND idempotency_key=?",owner,key);
        if(!old.isEmpty()){
            if(!product.equals(old.get(0).get("product_code")))throw error(409,"幂等键已用于另一商品");
            return detail(owner,number(old.get(0),"order_id"));
        }
        String orderNo="LOCAL-TEST-"+UUID.randomUUID().toString().replace("-","");
        BigDecimal price=amount(p);if(price.signum()<=0)throw error(409,"商品价格不正确");
        db.update("INSERT INTO order_info(user_id,order_title,order_no,order_status,original_amount,order_amount,item_type,pay_way,create_time) VALUES(?,?,?,'0901',?,?,'1001','1199',?)",owner,p.get("title"),orderNo,price,price,now());
        long id=db.queryForObject("SELECT id FROM order_info WHERE order_no=?",Long.class,orderNo);
        db.update("INSERT INTO local_checkout VALUES(?,?,?,?,?)",id,owner,product,key,Timestamp.from(clock.instant().plusSeconds(900)));
        db.update("INSERT INTO local_payment VALUES(?,?,?,'PENDING',?,?)",UUID.randomUUID().toString(),id,price,now(),now());
        event(id,"CREATED",owner);return detail(owner,id);
    }
    public Map<String,Object> detail(long owner,long id){
        var o=owned(owner,id,false);var p=one("SELECT * FROM local_payment WHERE order_id=?",id);
        var refunds=db.queryForList("SELECT id,status,attempts,last_error,available_at FROM local_refund_job WHERE order_id=?",id);
        return Map.of("orderId",Long.toString(id),"orderNo",o.get("order_no"),"title",o.get("order_title"),"amount",amount(p).toPlainString(),
                "status",o.get("order_status"),"paymentId",p.get("id"),"paymentStatus",p.get("status"),"expiresAt",instant(o.get("expires_at")).toString(),"channel","LOCAL_SIMULATOR","refunds",refunds);
    }
    @Transactional public Map<String,Object> cancel(long owner,long id){
        var o=owned(owner,id,true);String status=(String)o.get("order_status");
        if(!List.of("0901","0903").contains(status))throw error(409,"已支付订单不能取消，请申请售后");
        close(id,"CANCELLED",owner);return detail(owner,id);
    }
    @Transactional public Map<String,Object> simulate(long owner,long id,String outcome){
        if(!List.of("SUCCESS","FAILED").contains(outcome))throw error(422,"模拟支付结果不正确");
        owned(owner,id,true);var p=one("SELECT * FROM local_payment WHERE order_id=? FOR UPDATE",id);
        var cb=new Callback("PAYMENT",(String)p.get("id"),UUID.randomUUID().toString(),amount(p).toPlainString(),outcome,clock.instant().getEpochSecond());
        return callback(cb,signature(cb));
    }
    private String canonical(Callback cb){return String.join("\n",cb.kind,cb.targetId,cb.receiptId,cb.amount,cb.outcome,Long.toString(cb.timestamp));}
    public String signature(Callback cb){
        if(secret.length()<32)throw error(503,"本地支付回调密钥尚未初始化");
        try{var mac=Mac.getInstance("HmacSHA256");mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8),"HmacSHA256"));return HexFormat.of().formatHex(mac.doFinal(canonical(cb).getBytes(StandardCharsets.UTF_8)));}
        catch(java.security.GeneralSecurityException e){throw new IllegalStateException("HMAC unavailable");}
    }
    @Transactional public Map<String,Object> callback(Callback cb,String signed){
        if(cb==null||cb.kind==null||cb.outcome==null||!List.of("PAYMENT","REFUND").contains(cb.kind)||!List.of("SUCCESS","FAILED").contains(cb.outcome)||
                cb.targetId==null||!cb.targetId.matches("[a-f0-9-]{36}")||cb.receiptId==null||!cb.receiptId.matches("[a-zA-Z0-9_-]{16,64}")||
                cb.amount==null||!cb.amount.matches("[0-9]{1,8}\\.[0-9]{2}"))throw error(422,"回调参数不正确");
        if(signed==null||!MessageDigest.isEqual(signature(cb).getBytes(StandardCharsets.UTF_8),signed.getBytes(StandardCharsets.UTF_8))||
                cb.timestamp<clock.instant().getEpochSecond()-300||cb.timestamp>clock.instant().getEpochSecond()+300)throw error(401,"回调签名无效或已过期");
        var target=one("SELECT * FROM "+(cb.kind.equals("PAYMENT")?"local_payment":"local_refund_job")+" WHERE id=?",cb.targetId);
        long orderId=number(target,"order_id");var ownerRow=one("SELECT user_id FROM order_info WHERE id=? AND is_deleted=0",orderId);
        long owner=number(ownerRow,"user_id");var order=owned(owner,orderId,true);
        var request=cb.kind.equals("REFUND")?one("SELECT * FROM after_sales_request WHERE id=? FOR UPDATE",cb.targetId):null;
        target=one("SELECT * FROM "+(cb.kind.equals("PAYMENT")?"local_payment":"local_refund_job")+" WHERE id=? FOR UPDATE",cb.targetId);
        if(amount(target).compareTo(new BigDecimal(cb.amount))!=0)throw error(409,"回调金额与交易快照不一致");
        if(amount(target).compareTo((BigDecimal)order.get("order_amount"))!=0)throw error(409,"订单金额已变化，拒绝处理回调");
        // Use a current read after the order lock; a previous plain read may have
        // opened a stale MySQL REPEATABLE READ snapshot during a concurrent replay.
        var receipts=db.queryForList("SELECT * FROM local_callback WHERE receipt_id=? FOR UPDATE",cb.receiptId);
        if(!receipts.isEmpty()){
            var r=receipts.get(0);if(!cb.kind.equals(r.get("kind"))||!cb.targetId.equals(r.get("target_id"))||!cb.outcome.equals(r.get("outcome"))||amount(r).compareTo(new BigDecimal(cb.amount))!=0)throw error(409,"回调编号已被其他结果使用");
            return detail(owner,orderId);
        }
        if(cb.kind.equals("PAYMENT")){
            if(!"SUCCEEDED".equals(target.get("status"))){
                if(expired(order)||"0903".equals(order.get("order_status"))){close(orderId,"EXPIRED",null);}
                else if(cb.outcome.equals("SUCCESS")){
                    if(!"0901".equals(order.get("order_status")))throw error(409,"订单不可支付");
                    db.update("UPDATE local_payment SET status='SUCCEEDED',update_time=? WHERE id=?",now(),cb.targetId);
                    db.update("UPDATE order_info SET order_status='0902' WHERE id=?",orderId);event(orderId,"PAYMENT_SUCCEEDED",null);
                }else{db.update("UPDATE local_payment SET status='FAILED',update_time=? WHERE id=?",now(),cb.targetId);event(orderId,"PAYMENT_FAILED",null);}
            }
        }else{
            if(cb.outcome.equals("FAILED"))throw error(422,"退款失败应通过重试队列处理");
            // A signed callback alone cannot invent a local provider refund receipt.
            var provider=one("SELECT * FROM local_provider_receipt WHERE refund_id=?",cb.targetId);
            if(!cb.receiptId.equals(provider.get("receipt_id"))||amount(provider).compareTo(new BigDecimal(cb.amount))!=0)throw error(409,"退款凭据不匹配");
            if(!"SUCCEEDED".equals(target.get("status"))){
                if(!List.of("REFUNDING","REFUND_FAILED").contains(request.get("status"))||!"0902".equals(order.get("order_status")))throw error(409,"当前申请不可退款");
                db.update("UPDATE local_refund_job SET status='SUCCEEDED',last_error=NULL,update_time=? WHERE id=?",now(),cb.targetId);
                db.update("UPDATE order_info SET order_status='0904' WHERE id=?",orderId);
                db.update("UPDATE after_sales_request SET status='REFUNDED',update_time=? WHERE id=?",now(),cb.targetId);
                db.update("INSERT INTO after_sales_event(request_id,user_id,event_type,create_time) VALUES(?,?,'REFUNDED',?)",cb.targetId,owner,now());
                event(orderId,"REFUND_SUCCEEDED",null);
            }
        }
        db.update("INSERT INTO local_callback VALUES(?,?,?,?,?,?)",cb.receiptId,cb.kind,cb.targetId,new BigDecimal(cb.amount),cb.outcome,now());
        return detail(owner,orderId);
    }
    @Transactional public Map<String,Object> enqueue(long actor,String rid,String scenario){
        if(!List.of("SUCCESS","FAIL_ONCE","TIMEOUT_ONCE","ALWAYS_FAIL").contains(scenario))throw error(422,"模拟退款场景不正确");
        var first=one("SELECT * FROM after_sales_request WHERE id=?",rid);long orderId=number(first,"order_id");
        owned(number(first,"user_id"),orderId,true);
        var r=one("SELECT * FROM after_sales_request WHERE id=? FOR UPDATE",rid);
        var p=one("SELECT * FROM local_payment WHERE order_id=? FOR UPDATE",orderId);
        if(!"SUCCEEDED".equals(p.get("status"))||amount(p).compareTo((BigDecimal)r.get("amount"))!=0)throw error(409,"只能退款已成功模拟支付且金额匹配的本地订单");
        var old=db.queryForList("SELECT * FROM local_refund_job WHERE id=? FOR UPDATE",rid);
        if(!old.isEmpty()&&!"FAILED".equals(old.get(0).get("status")))return old.get(0);
        if(!List.of("APPROVED","REFUND_FAILED").contains(r.get("status")))throw error(409,"申请尚未审核通过或不可重试");
        if(old.isEmpty())db.update("INSERT INTO local_refund_job(id,order_id,payment_id,amount,status,scenario,available_at,actor_id,create_time,update_time) VALUES(?,?,?,?,'PENDING',?,?,?,?,?)",rid,orderId,p.get("id"),amount(p),scenario,now(),actor,now(),now());
        else db.update("UPDATE local_refund_job SET status='PENDING',attempts=0,scenario=?,available_at=?,last_error=NULL,actor_id=?,update_time=? WHERE id=?",scenario,now(),actor,now(),rid);
        db.update("UPDATE after_sales_request SET status='REFUNDING',update_time=? WHERE id=?",now(),rid);
        db.update("INSERT INTO after_sales_event(request_id,user_id,actor_id,event_type,create_time) VALUES(?,?,?,'REFUNDING',?)",rid,number(r,"user_id"),actor,now());
        event(orderId,"REFUND_ENQUEUED",actor);return one("SELECT * FROM local_refund_job WHERE id=?",rid);
    }
    public List<String> due(){return db.queryForList("SELECT id FROM local_refund_job WHERE status IN ('PENDING','PROCESSING') AND available_at<=? ORDER BY available_at LIMIT 10",String.class,now());}
    @Transactional public Map<String,Object> claim(String rid){
        var f=one("SELECT * FROM local_refund_job WHERE id=?",rid);
        one("SELECT * FROM order_info WHERE id=? FOR UPDATE",f.get("order_id"));
        var r=one("SELECT * FROM local_refund_job WHERE id=? FOR UPDATE",rid);
        if(!List.of("PENDING","PROCESSING").contains(r.get("status"))||instant(r.get("available_at")).isAfter(clock.instant()))return null;
        if(number(r,"attempts")>=5){failJob(r,"重试次数耗尽");return null;}
        db.update("UPDATE local_refund_job SET status='PROCESSING',attempts=attempts+1,available_at=?,update_time=? WHERE id=?",Timestamp.from(clock.instant().plusSeconds(30)),now(),rid);
        return one("SELECT * FROM local_refund_job WHERE id=?",rid);
    }
    private void failJob(Map<String,Object> r,String reason){
        db.update("UPDATE local_refund_job SET status='FAILED',last_error=?,update_time=? WHERE id=?",reason,now(),r.get("id"));
        db.update("UPDATE after_sales_request SET status='REFUND_FAILED',update_time=? WHERE id=?",now(),r.get("id"));
        var a=one("SELECT user_id FROM after_sales_request WHERE id=?",r.get("id"));
        db.update("INSERT INTO after_sales_event(request_id,user_id,event_type,create_time) VALUES(?,?,'REFUND_FAILED',?)",r.get("id"),a.get("user_id"),now());
    }
    @Transactional public void retry(String rid,int attempt,String reason){
        var f=one("SELECT * FROM local_refund_job WHERE id=?",rid);one("SELECT * FROM order_info WHERE id=? FOR UPDATE",f.get("order_id"));
        var r=one("SELECT * FROM local_refund_job WHERE id=? FOR UPDATE",rid);
        if(!"PROCESSING".equals(r.get("status"))||number(r,"attempts")!=attempt)return;
        if(attempt>=5){failJob(r,reason);return;}
        db.update("UPDATE local_refund_job SET status='PENDING',last_error=?,available_at=?,update_time=? WHERE id=?",reason,Timestamp.from(clock.instant().plusSeconds(Math.min(60,2L<<attempt))),now(),rid);
    }
    @Transactional public void expire(){
        for(var r:db.queryForList("SELECT c.order_id,o.user_id FROM local_checkout c JOIN order_info o ON o.id=c.order_id WHERE c.expires_at<=? AND o.order_status='0901' LIMIT 50",now())){
            var o=owned(number(r,"user_id"),number(r,"order_id"),true);
            if(expired(o))close(number(r,"order_id"),"EXPIRED",null);
        }
    }
    public List<Map<String,Object>> jobs(){return db.queryForList("SELECT * FROM local_refund_job ORDER BY create_time DESC LIMIT 50");}
    public List<Map<String,Object>> events(long owner,long orderId){owned(owner,orderId,false);return db.queryForList("SELECT event_type,actor_id,create_time FROM local_transaction_event WHERE order_id=? ORDER BY id",orderId);}
}
