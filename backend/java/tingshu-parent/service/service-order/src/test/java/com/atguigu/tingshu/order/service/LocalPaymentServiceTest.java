package com.atguigu.tingshu.order.service;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.test.context.junit.jupiter.SpringJUnitConfig;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.web.server.ResponseStatusException;
import javax.sql.DataSource;
import java.time.*;
import java.util.*;
import java.nio.charset.StandardCharsets;
import static org.junit.jupiter.api.Assertions.*;

@SpringJUnitConfig(LocalPaymentServiceTest.Config.class)
class LocalPaymentServiceTest {
 static class TestClock extends Clock {Instant now;public ZoneId getZone(){return ZoneOffset.UTC;}public Clock withZone(ZoneId z){return this;}public Instant instant(){return now;}}
 @Configuration @EnableTransactionManagement static class Config {
  @Bean DataSource source(){return new DriverManagerDataSource("jdbc:h2:mem:payments;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");}
  @Bean JdbcTemplate db(DataSource d){return new JdbcTemplate(d);}
  @Bean DataSourceTransactionManager transactionManager(DataSource d){return new DataSourceTransactionManager(d);}
  @Bean TestClock clock(){return new TestClock();}
  @Bean LocalPaymentService payments(JdbcTemplate d,TestClock c){return new LocalPaymentService(d,c,"private-test-key-at-least-32-characters");}
  @Bean AssistantOrderService orders(JdbcTemplate d,TestClock c){return new AssistantOrderService(d,c);}
  @Bean LocalRefundGateway gateway(JdbcTemplate d){return new LocalRefundGateway(d);}
 }
 @Autowired LocalPaymentService service;@Autowired AssistantOrderService orders;@Autowired LocalRefundGateway gateway;@Autowired JdbcTemplate db;@Autowired TestClock clock;
 @BeforeEach void setup() throws Exception {
  clock.now=Instant.now();db.execute("DROP ALL OBJECTS");
  db.execute("CREATE TABLE order_info(id BIGINT AUTO_INCREMENT PRIMARY KEY,user_id BIGINT,order_title VARCHAR(100),order_no VARCHAR(50) UNIQUE,order_status CHAR(4),original_amount DECIMAL(10,2),order_amount DECIMAL(10,2),item_type CHAR(4),pay_way CHAR(4),create_time TIMESTAMP,is_deleted INT DEFAULT 0)");
  db.execute("CREATE TABLE after_sales_request(id CHAR(36) PRIMARY KEY,user_id BIGINT,order_id BIGINT,order_no VARCHAR(50),order_title VARCHAR(100),amount DECIMAL(10,2),reason VARCHAR(300),status VARCHAR(20),expires_at TIMESTAMP,create_time TIMESTAMP,update_time TIMESTAMP,submitted_at TIMESTAMP,review_note VARCHAR(500),reviewer_id BIGINT,reviewed_at TIMESTAMP)");
  db.execute("CREATE TABLE after_sales_event(id BIGINT AUTO_INCREMENT PRIMARY KEY,request_id CHAR(36),user_id BIGINT,actor_id BIGINT,event_type VARCHAR(20),create_time TIMESTAMP)");
  String schema=new String(getClass().getResourceAsStream("/local-payments.sql").readAllBytes(),StandardCharsets.UTF_8);
  for(String statement:schema.split(";"))if(!statement.isBlank())db.execute(statement);
 }
 Map<String,Object> checkout(){return service.checkout(42,"listening-demo",UUID.randomUUID().toString());}
 long id(Map<String,Object> o){return Long.parseLong((String)o.get("orderId"));}
 LocalPaymentService.Callback callback(Map<String,Object> o,String receipt,String amount,String outcome){return new LocalPaymentService.Callback("PAYMENT",(String)o.get("paymentId"),receipt,amount,outcome,clock.instant().getEpochSecond());}
 void fails(int code,Runnable action){assertEquals(code,assertThrows(ResponseStatusException.class,action::run).getStatusCode().value());}
 int count(String table){return db.queryForObject("SELECT COUNT(*) FROM "+table,Integer.class);}
 String approval(Map<String,Object> o){service.simulate(42,id(o),"SUCCESS");var r=orders.prepare(42,id(o),"本地退款测试申请");orders.confirm(42,r.id());orders.review(900010,r.id(),"APPROVED","本地测试审核通过");return r.id();}
 void acknowledge(String rid,Map<String,Object> receipt){var c=new LocalPaymentService.Callback("REFUND",rid,(String)receipt.get("receipt_id"),"9.90","SUCCESS",clock.instant().getEpochSecond());service.callback(c,service.signature(c));}
 @Test void checkoutUsesPriceSnapshotAndIsIdempotent(){String key=UUID.randomUUID().toString();var first=service.checkout(42,"listening-demo",key);db.update("UPDATE local_product SET amount=15 WHERE code='listening-demo'");assertEquals(first.get("orderId"),service.checkout(42,"listening-demo",key).get("orderId"));assertEquals("9.90",first.get("amount"));assertEquals(1,count("order_info"));assertEquals("15.00",checkout().get("amount"));}
 @Test void ownershipAndPaidCancellation(){var o=checkout();fails(404,()->service.simulate(43,id(o),"SUCCESS"));fails(404,()->service.detail(43,id(o)));service.simulate(42,id(o),"SUCCESS");fails(409,()->service.cancel(42,id(o)));}
 @Test void signatureAndAmountAreEnforced(){var o=checkout();var c=callback(o,UUID.randomUUID().toString(),"9.90","SUCCESS");fails(401,()->service.callback(c,"forged"));var wrong=callback(o,UUID.randomUUID().toString(),"0.01","SUCCESS");fails(409,()->service.callback(wrong,service.signature(wrong)));assertEquals("0901",service.detail(42,id(o)).get("status"));assertEquals(0,count("local_callback"));}
 @Test void expiredSignaturesAndMalformedBodiesFail(){var o=checkout();var c=callback(o,UUID.randomUUID().toString(),"9.90","SUCCESS");clock.now=clock.now.plusSeconds(301);fails(401,()->service.callback(c,service.signature(c)));fails(422,()->service.callback(new LocalPaymentService.Callback(null,null,null,null,null,0),"invalid"));}
 @Test void callbackReplayCreatesOnePaymentEvent(){var o=checkout();var c=callback(o,UUID.randomUUID().toString(),"9.90","SUCCESS");service.callback(c,service.signature(c));service.callback(c,service.signature(c));service.simulate(42,id(o),"FAILED");assertEquals("SUCCEEDED",service.detail(42,id(o)).get("paymentStatus"));assertEquals(1,db.queryForObject("SELECT COUNT(*) FROM local_transaction_event WHERE event_type='PAYMENT_SUCCEEDED'",Integer.class));}
 @Test void callbackReceiptCannotBeRebound(){var a=checkout();var b=checkout();String receipt=UUID.randomUUID().toString();var c=callback(a,receipt,"9.90","SUCCESS");service.callback(c,service.signature(c));var d=callback(b,receipt,"9.90","SUCCESS");fails(409,()->service.callback(d,service.signature(d)));assertEquals("0901",service.detail(42,id(b)).get("status"));}
 @Test void paymentFailureCanRetryButCancelledCannotPay(){var o=checkout();service.simulate(42,id(o),"FAILED");assertEquals("FAILED",service.detail(42,id(o)).get("paymentStatus"));service.simulate(42,id(o),"SUCCESS");assertEquals("0902",service.detail(42,id(o)).get("status"));var b=checkout();service.cancel(42,id(b));service.simulate(42,id(b),"SUCCESS");assertEquals("0903",service.detail(42,id(b)).get("status"));}
 @Test void latePaymentAndSchedulerCloseOnlyLocalUnpaidOrders(){var o=checkout();clock.now=clock.now.plusSeconds(901);service.simulate(42,id(o),"SUCCESS");assertEquals("0903",service.detail(42,id(o)).get("status"));var paid=checkout();service.simulate(42,id(paid),"SUCCESS");var unpaid=checkout();clock.now=clock.now.plusSeconds(901);service.expire();assertEquals("0903",service.detail(42,id(unpaid)).get("status"));assertEquals("0902",service.detail(42,id(paid)).get("status"));}
 @Test void refundRequiresReviewAndCannotRefundCourseOrder(){var o=checkout();service.simulate(42,id(o),"SUCCESS");var r=orders.prepare(42,id(o),"本地退款测试申请");orders.confirm(42,r.id());fails(409,()->service.enqueue(1,r.id(),"SUCCESS"));assertEquals(0,count("local_refund_job"));}
 @Test void lostProviderResponseIsReconciledWithoutDuplicateRefund(){var o=checkout();String rid=approval(o);service.enqueue(900010,rid,"TIMEOUT_ONCE");service.enqueue(900010,rid,"TIMEOUT_ONCE");var job=service.claim(rid);var receipt=gateway.execute(job);service.retry(rid,1,"响应丢失");assertEquals("REFUNDING",orders.requests(42).get(0).status());clock.now=clock.now.plusSeconds(5);job=service.claim(rid);assertEquals(receipt.get("receipt_id"),gateway.execute(job).get("receipt_id"));acknowledge(rid,receipt);acknowledge(rid,receipt);assertEquals(1,count("local_provider_receipt"));assertEquals("REFUNDED",orders.requests(42).get(0).status());assertEquals("0904",service.detail(42,id(o)).get("status"));}
 @Test void processingLeaseCanRecoverAfterRestart(){var o=checkout();String rid=approval(o);service.enqueue(900010,rid,"SUCCESS");var first=service.claim(rid);assertNull(service.claim(rid));clock.now=clock.now.plusSeconds(31);var recovered=service.claim(rid);assertEquals(2,((Number)recovered.get("attempts")).intValue());service.retry(rid,1,"过期工作进程");assertEquals("PROCESSING",service.jobs().get(0).get("status"));acknowledge(rid,gateway.execute(recovered));}
 @Test void retryLimitFailsAndAdministratorCanRetry(){var o=checkout();String rid=approval(o);service.enqueue(900010,rid,"ALWAYS_FAIL");for(int n=1;n<=5;n++){var j=service.claim(rid);assertTrue(gateway.execute(j).containsKey("failed"));service.retry(rid,n,"模拟失败");clock.now=clock.now.plusSeconds(65);}assertEquals("REFUND_FAILED",orders.requests(42).get(0).status());assertNull(service.claim(rid));service.enqueue(900010,rid,"SUCCESS");acknowledge(rid,gateway.execute(service.claim(rid)));assertEquals("REFUNDED",orders.requests(42).get(0).status());}
 @Test void auditFailureRollsBackPayment(){var o=checkout();db.execute("DROP TABLE local_transaction_event");assertThrows(Exception.class,()->service.simulate(42,id(o),"SUCCESS"));assertEquals("0901",service.detail(42,id(o)).get("status"));assertEquals("PENDING",service.detail(42,id(o)).get("paymentStatus"));assertEquals(0,count("local_callback"));}
}
