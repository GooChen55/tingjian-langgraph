package com.atguigu.tingshu.order.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.context.junit.jupiter.SpringJUnitConfig;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.beans.factory.annotation.Autowired;
import javax.sql.DataSource;
import java.time.*;
import static org.junit.jupiter.api.Assertions.*;

@SpringJUnitConfig(AssistantOrderServiceTest.Config.class)
class AssistantOrderServiceTest {
    static class TestClock extends Clock {
        Instant now = Instant.parse("2026-10-10T03:00:00Z");
        public ZoneId getZone() { return ZoneOffset.UTC; }
        public Clock withZone(ZoneId zone) { return this; }
        public Instant instant() { return now; }
    }
    @Configuration @EnableTransactionManagement
    static class Config {
        @Bean DataSource dataSource() { return new DriverManagerDataSource("jdbc:h2:mem:aftersales;MODE=MySQL;DB_CLOSE_DELAY=-1", "sa", ""); }
        @Bean JdbcTemplate db(DataSource source) { return new JdbcTemplate(source); }
        @Bean DataSourceTransactionManager transactionManager(DataSource source) { return new DataSourceTransactionManager(source); }
        @Bean TestClock clock() { return new TestClock(); }
        @Bean AssistantOrderService service(JdbcTemplate db, TestClock clock) { return new AssistantOrderService(db, clock); }
    }
    @Autowired AssistantOrderService service;
    @Autowired JdbcTemplate db;
    @Autowired TestClock clock;
    @BeforeEach void setup() {
        clock.now = Instant.parse("2026-10-10T03:00:00Z");
        db.execute("DROP ALL OBJECTS");
        db.execute("CREATE TABLE order_info(id BIGINT PRIMARY KEY,user_id BIGINT,order_no VARCHAR(50),order_title VARCHAR(100),order_status VARCHAR(4),order_amount DECIMAL(10,2),create_time TIMESTAMP,is_deleted INT)");
        db.execute("CREATE TABLE after_sales_request(id CHAR(36) PRIMARY KEY,user_id BIGINT,order_id BIGINT,order_no VARCHAR(50),order_title VARCHAR(100),amount DECIMAL(10,2),reason VARCHAR(300),status VARCHAR(20),expires_at TIMESTAMP,create_time TIMESTAMP,update_time TIMESTAMP,submitted_at TIMESTAMP,review_note VARCHAR(500),reviewer_id BIGINT,reviewed_at TIMESTAMP)");
        db.execute("CREATE TABLE after_sales_event(id BIGINT AUTO_INCREMENT PRIMARY KEY,request_id CHAR(36),user_id BIGINT,actor_id BIGINT,event_type VARCHAR(20),create_time TIMESTAMP)");
        db.update("INSERT INTO order_info VALUES(1,42,'mine','测试订单','0902',29.90,CURRENT_TIMESTAMP,0),(2,43,'other','别人的订单','0902',20,CURRENT_TIMESTAMP,0),(3,42,'unpaid','未支付','0901',20,CURRENT_TIMESTAMP,0),(4,42,'deleted','已删除','0902',20,CURRENT_TIMESTAMP,1)");
    }
    private void fails(int status, Runnable action) {
        assertEquals(status, assertThrows(ResponseStatusException.class, action::run).getStatusCode().value());
    }
    private int events(String type) { return db.queryForObject("SELECT COUNT(*) FROM after_sales_event WHERE event_type=?", Integer.class, type); }

    @Test void ownershipAndDeletionAreEnforced() {
        assertEquals(2, service.orders(42).size());
        assertEquals("29.90", service.orders(42).stream().filter(r -> r.id().equals("1")).findFirst().orElseThrow().amount());
        fails(404, () -> service.prepare(42, 2, "买错了这个专辑"));
        fails(404, () -> service.prepare(42, 4, "买错了这个专辑"));
        assertEquals(0, db.queryForObject("SELECT COUNT(*) FROM after_sales_request", Integer.class));
    }
    @Test void unpaidAndZeroAmountCannotPrepare() {
        fails(409, () -> service.prepare(42, 3, "买错了这个专辑"));
        db.update("UPDATE order_info SET order_amount=0 WHERE id=1");
        fails(409, () -> service.prepare(42, 1, "买错了这个专辑"));
    }
    @Test void prepareIsNotSubmissionAndRepeatedRequestReusesDraft() {
        var draft = service.prepare(42, 1, "  买错了这个专辑  ");
        assertEquals("DRAFT", draft.status());
        assertNull(draft.submittedAt());
        assertEquals(draft.id(), service.prepare(42, 1, "买错了这个专辑").id());
        assertEquals(1, events("PREPARED"));
        assertEquals(0, events("CONFIRMED"));
        fails(409, () -> service.prepare(42, 1, "专辑无法正常播放"));
        fails(422, () -> service.prepare(42, 1, "     "));
    }
    @Test void confirmationIsIdempotentAndDoesNotRefundOrder() {
        var draft = service.prepare(42, 1, "买错了这个专辑");
        assertEquals("SUBMITTED", service.confirm(42, draft.id()).status());
        assertEquals("SUBMITTED", service.confirm(42, draft.id()).status());
        assertEquals(1, events("CONFIRMED"));
        assertEquals("0902", db.queryForObject("SELECT order_status FROM order_info WHERE id=1", String.class));
        assertEquals(1, service.requests(42).size());
        assertEquals(0, service.requests(43).size());
    }
    @Test void otherUsersCannotConfirmOrWithdraw() {
        var draft = service.prepare(42, 1, "买错了这个专辑");
        fails(404, () -> service.confirm(43, draft.id()));
        fails(404, () -> service.withdraw(43, draft.id()));
        assertEquals("DRAFT", service.requests(42).get(0).status());
    }
    @Test void expiredDraftCannotSubmitAndCanPrepareAgain() {
        var draft = service.prepare(42, 1, "买错了这个专辑");
        clock.now = clock.now.plusSeconds(600);
        fails(410, () -> service.confirm(42, draft.id()));
        assertEquals("EXPIRED", service.requests(42).get(0).status());
        assertNotEquals(draft.id(), service.prepare(42, 1, "买错了这个专辑").id());
        assertEquals(0, events("CONFIRMED"));
    }
    @Test void paymentAndAmountAreRecheckedAtConfirmation() {
        var draft = service.prepare(42, 1, "买错了这个专辑");
        db.update("UPDATE order_info SET order_status='0903' WHERE id=1");
        fails(409, () -> service.confirm(42, draft.id()));
        db.update("UPDATE order_info SET order_status='0902',order_amount=25 WHERE id=1");
        fails(409, () -> service.confirm(42, draft.id()));
        assertEquals(0, events("CONFIRMED"));
    }
    @Test void withdrawalIsDurableAndAllowsNewRequest() {
        var draft = service.prepare(42, 1, "买错了这个专辑");
        service.confirm(42, draft.id());
        assertEquals("WITHDRAWN", service.withdraw(42, draft.id()).status());
        assertEquals("WITHDRAWN", service.withdraw(42, draft.id()).status());
        assertEquals(1, events("WITHDRAWN"));
        fails(409, () -> service.confirm(42, draft.id()));
        assertNotEquals(draft.id(), service.prepare(42, 1, "买错了这个专辑").id());
    }
    @Test void failedAuditInsertRollsBackRequest() {
        db.execute("DROP TABLE after_sales_event");
        assertThrows(Exception.class, () -> service.prepare(42, 1, "买错了这个专辑"));
        assertEquals(0, db.queryForObject("SELECT COUNT(*) FROM after_sales_request", Integer.class));
    }
    @Test void approveIsIdempotentAndDoesNotExecuteRefund() {
        var draft=service.prepare(42,1,"买错了这个专辑");service.confirm(42,draft.id());
        var result=service.review(99,draft.id(),"APPROVED","核对订单后同意申请");
        assertEquals("APPROVED",result.status());assertEquals("核对订单后同意申请",result.reviewNote());
        assertTrue(result.statusLabel().contains("尚未退款"));
        service.review(99,draft.id(),"APPROVED","核对订单后同意申请");assertEquals(1,events("APPROVED"));
        fails(409,()->service.withdraw(42,draft.id()));fails(409,()->service.prepare(42,1,"重新申请这个订单"));
        assertEquals("0902",db.queryForObject("SELECT order_status FROM order_info WHERE id=1",String.class));
    }
    @Test void rejectPersistsReasonAndAllowsNewRequest() {
        var draft=service.prepare(42,1,"买错了这个专辑");service.confirm(42,draft.id());
        service.review(99,draft.id(),"REJECTED","当前申请缺少必要说明");
        assertEquals("REJECTED",service.requests(42).get(0).status());
        assertEquals("当前申请缺少必要说明",service.requests(42).get(0).reviewNote());
        fails(409,()->service.review(99,draft.id(),"APPROVED","重新审核同意申请"));
        assertNotEquals(draft.id(),service.prepare(42,1,"补充完整原因重新申请").id());
    }
    @Test void draftAndWithdrawnCannotBeReviewed() {
        var draft=service.prepare(42,1,"买错了这个专辑");
        fails(409,()->service.review(99,draft.id(),"APPROVED","同意售后申请登记"));
        service.confirm(42,draft.id());service.withdraw(42,draft.id());
        fails(409,()->service.review(99,draft.id(),"APPROVED","同意售后申请登记"));
    }
    @Test void reviewAuditFailureRollsBackDecision() {
        var draft=service.prepare(42,1,"买错了这个专辑");service.confirm(42,draft.id());db.execute("DROP TABLE after_sales_event");
        assertThrows(Exception.class,()->service.review(99,draft.id(),"APPROVED","同意售后申请登记"));
        assertEquals("SUBMITTED",service.requests(42).get(0).status());
    }
    @Test void paginationIsBoundedAndOwned() {
        var draft=service.prepare(42,1,"买错了这个专辑");
        assertEquals(2L,service.ordersPage(42,1,1).get("total"));
        assertEquals(0L,service.requestsPage(43L,null,1,10).get("total"));
        fails(422,()->service.requestsPage(null,null,0,10));fails(422,()->service.requestsPage(null,null,1,51));
    }
    @Test void expiredFilterIncludesLogicallyExpiredDrafts() {
        service.prepare(42,1,"买错了这个专辑");clock.now=clock.now.plusSeconds(600);
        assertEquals(0L,service.requestsPage(null,"DRAFT",1,10).get("total"));
        assertEquals(1L,service.requestsPage(null,"EXPIRED",1,10).get("total"));
    }
    @Test void approvalRechecksOrderPaymentAndAmount() {
        var draft=service.prepare(42,1,"买错了这个专辑");service.confirm(42,draft.id());
        db.update("UPDATE order_info SET order_status='0903' WHERE id=1");
        fails(409,()->service.review(99,draft.id(),"APPROVED","核对申请同意审核"));
        db.update("UPDATE order_info SET order_status='0902',order_amount=25 WHERE id=1");
        fails(409,()->service.review(99,draft.id(),"APPROVED","核对申请同意审核"));
        assertEquals("SUBMITTED",service.requests(42).get(0).status());
        assertEquals(0,events("APPROVED"));
    }
}
