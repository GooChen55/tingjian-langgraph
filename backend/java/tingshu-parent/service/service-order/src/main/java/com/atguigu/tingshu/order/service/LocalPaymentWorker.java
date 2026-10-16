package com.atguigu.tingshu.order.service;
import org.springframework.context.annotation.*;
import org.springframework.scheduling.annotation.*;
import org.springframework.stereotype.Component;
import org.slf4j.*;
import java.math.BigDecimal;
import java.time.Instant;
@Configuration @Profile({"local","vm"}) @EnableScheduling
class LocalPaymentScheduling {}
@Component @Profile({"local","vm"})
public class LocalPaymentWorker {
 private static final Logger log=LoggerFactory.getLogger(LocalPaymentWorker.class);
 private final LocalPaymentService service;private final LocalRefundGateway gateway;
 public LocalPaymentWorker(LocalPaymentService service,LocalRefundGateway gateway){this.service=service;this.gateway=gateway;}
 @Scheduled(fixedDelayString="${listening.local-payment.worker-delay:2000}") public void tick(){
  try{service.expire();for(String id:service.due())dispatch(id);}catch(Exception e){log.warn("Local payment maintenance failed: {}",e.getClass().getSimpleName());}
 }
 public void dispatch(String id){
  var job=service.claim(id);if(job==null)return;int attempt=((Number)job.get("attempts")).intValue();
  try{
   var receipt=gateway.execute(job);if(receipt.containsKey("failed")){service.retry(id,attempt,"本地渠道模拟失败");return;}
   if("TIMEOUT_ONCE".equals(job.get("scenario"))&&attempt==1){service.retry(id,attempt,"本地渠道已受理但模拟响应丢失");return;}
   var cb=new LocalPaymentService.Callback("REFUND",id,(String)receipt.get("receipt_id"),((BigDecimal)receipt.get("amount")).toPlainString(),"SUCCESS",Instant.now().getEpochSecond());
   service.callback(cb,service.signature(cb));
  }catch(Exception e){service.retry(id,attempt,"本地渠道处理异常，等待重试");log.warn("Local refund retry id={} attempt={} error={}",id,attempt,e.getClass().getSimpleName());}
 }
}
