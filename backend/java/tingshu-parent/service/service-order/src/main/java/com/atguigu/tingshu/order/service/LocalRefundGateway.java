package com.atguigu.tingshu.order.service;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.math.BigDecimal;
import java.util.*;
/** Durable mock provider ledger, committed separately from business acknowledgement. */
@Service @Profile({"local","vm"})
public class LocalRefundGateway {
 private final JdbcTemplate db;
 public LocalRefundGateway(JdbcTemplate db){this.db=db;}
 @Transactional public Map<String,Object> execute(Map<String,Object> job){
  String id=(String)job.get("id"),scenario=(String)job.get("scenario");int attempts=((Number)job.get("attempts")).intValue();
  var old=db.queryForList("SELECT * FROM local_provider_receipt WHERE refund_id=?",id);if(!old.isEmpty())return old.get(0);
  if("ALWAYS_FAIL".equals(scenario)||("FAIL_ONCE".equals(scenario)&&attempts==1))return Map.of("failed",true);
  db.update("INSERT IGNORE INTO local_provider_receipt VALUES(?,?,?,CURRENT_TIMESTAMP)",id,UUID.randomUUID().toString(),(BigDecimal)job.get("amount"));
  return db.queryForList("SELECT * FROM local_provider_receipt WHERE refund_id=?",id).get(0);
 }
}
