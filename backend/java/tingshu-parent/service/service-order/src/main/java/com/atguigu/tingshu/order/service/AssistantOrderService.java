package com.atguigu.tingshu.order.service;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.Map;

/** 订单归属和售后状态由 Java 控制，模型只有查询和生成草稿能力。 */
@Service
public class AssistantOrderService {
    private final JdbcTemplate db;
    private final Clock clock;
    @Autowired
    public AssistantOrderService(JdbcTemplate db) { this(db, Clock.systemUTC()); }
    AssistantOrderService(JdbcTemplate db, Clock clock) { this.db = db; this.clock = clock; }

    public record OrderView(String id, String orderNo, String title, String status,
                            String statusLabel, String amount, String createdAt, boolean demo) {}
    public record RequestView(String id, String orderId, String orderNo, String title,
                              String amount, String reason, String status, String statusLabel,
                              String expiresAt, String createdAt, String submittedAt, boolean demo,
                              String reviewNote, String reviewedAt) {}
    private record Order(long id, String number, String title, String status, BigDecimal amount, Instant created) {}
    private record Request(String id, long orderId, String number, String title, BigDecimal amount,
                           String reason, String status, Instant expires, Instant created, Instant submitted,
                           String reviewNote, Instant reviewed) {}
    private static String time(Instant value) { return value == null ? null : value.toString(); }
    private static Instant instant(ResultSet row, String field) throws SQLException {
        Timestamp value = row.getTimestamp(field); return value == null ? null : value.toInstant();
    }
    private Order orderRow(ResultSet row, int index) throws SQLException {
        return new Order(row.getLong("id"), row.getString("order_no"), row.getString("order_title"),
                row.getString("order_status"), row.getBigDecimal("order_amount"), instant(row, "create_time"));
    }
    private Request requestRow(ResultSet row, int index) throws SQLException {
        return new Request(row.getString("id"), row.getLong("order_id"), row.getString("order_no"),
                row.getString("order_title"), row.getBigDecimal("amount"), row.getString("reason"),
                row.getString("status"), instant(row, "expires_at"), instant(row, "create_time"), instant(row, "submitted_at"),
                row.getString("review_note"), instant(row,"reviewed_at"));
    }
    private Order order(long owner, long id, boolean lock) {
        var rows = db.query("SELECT * FROM order_info WHERE user_id=? AND id=? AND is_deleted=0" +
                (lock ? " FOR UPDATE" : ""), this::orderRow, owner, id);
        if (rows.isEmpty()) throw error(HttpStatus.NOT_FOUND, "订单不存在");
        return rows.get(0);
    }
    private Request request(long owner, String id, boolean lock) {
        var rows = db.query("SELECT * FROM after_sales_request WHERE user_id=? AND id=?" +
                (lock ? " FOR UPDATE" : ""), this::requestRow, owner, id);
        if (rows.isEmpty()) throw error(HttpStatus.NOT_FOUND, "售后申请不存在");
        return rows.get(0);
    }
    private RequestView view(long owner, Request row) {
        String status = row.status.equals("DRAFT") && !row.expires.isAfter(clock.instant()) ? "EXPIRED" : row.status;
        String label = switch (status) {
            case "DRAFT" -> "待确认，尚未提交";
            case "SUBMITTED" -> "已登记，待人工审核";
            case "WITHDRAWN" -> "已撤回";
            case "EXPIRED" -> "确认已过期，尚未提交";
            case "APPROVED" -> "审核通过，尚未退款";
            case "REJECTED" -> "审核未通过";
            case "REFUNDING" -> "本地模拟退款处理中";
            case "REFUNDED" -> "本地模拟退款成功（无真实资金）";
            case "REFUND_FAILED" -> "本地模拟退款失败，等待管理员重试";
            default -> "未知状态";
        };
        return new RequestView(row.id, Long.toString(row.orderId), row.number, row.title, row.amount.toPlainString(),
                row.reason, status, label, time(row.expires), time(row.created), time(row.submitted), owner == 900001,
                row.reviewNote, time(row.reviewed));
    }
    private static ResponseStatusException error(HttpStatus status, String message) {
        return new ResponseStatusException(status, message);
    }
    private void eligible(Order order) {
        if (!order.status.equals("0902") || order.amount.signum() <= 0)
            throw error(HttpStatus.CONFLICT, "仅支持为已支付且金额大于零的订单登记售后申请");
    }
    private void event(long owner, String id, String type) {
        db.update("INSERT INTO after_sales_event(request_id,user_id,event_type,create_time) VALUES(?,?,?,?)",
                id, owner, type, Timestamp.from(clock.instant()));
    }

    public List<OrderView> orders(long owner) {
        return db.query("SELECT * FROM order_info WHERE user_id=? AND is_deleted=0 ORDER BY create_time DESC,id DESC LIMIT 20",
                this::orderRow, owner).stream().map(row -> new OrderView(Long.toString(row.id), row.number, row.title,
                row.status, switch (row.status) { case "0901" -> "未支付"; case "0902" -> "已支付";
                    case "0903" -> "已取消"; case "0904" -> "本地模拟退款成功"; default -> "未知状态"; }, row.amount.toPlainString(), time(row.created), owner == 900001)).toList();
    }
    public List<RequestView> requests(long owner) {
        return db.query("SELECT * FROM after_sales_request WHERE user_id=? ORDER BY create_time DESC,id DESC LIMIT 20",
                this::requestRow, owner).stream().map(row -> view(owner, row)).toList();
    }

    @Transactional
    public RequestView prepare(long owner, long orderId, String reason) {
        reason = reason == null ? "" : reason.strip();
        if (reason.length() < 5 || reason.length() > 300)
            throw error(HttpStatus.UNPROCESSABLE_ENTITY, "请填写 5 至 300 字的售后原因");
        Order order = order(owner, orderId, true);
        eligible(order);
        // 所有同一订单的转换先锁订单行：并发草稿和确认都使用相同的锁顺序。
        db.update("UPDATE after_sales_request SET status='EXPIRED',update_time=? WHERE user_id=? AND order_id=? AND status='DRAFT' AND expires_at<=?",
                Timestamp.from(clock.instant()), owner, orderId, Timestamp.from(clock.instant()));
        var active = db.query("SELECT * FROM after_sales_request WHERE user_id=? AND order_id=? AND status IN ('DRAFT','SUBMITTED','APPROVED','REFUNDING','REFUND_FAILED') FOR UPDATE",
                this::requestRow, owner, orderId);
        if (!active.isEmpty()) {
            Request current = active.get(0);
            if (current.status.equals("DRAFT") && current.reason.equals(reason) && current.amount.compareTo(order.amount) == 0)
                return view(owner, current);
            throw error(HttpStatus.CONFLICT, "该订单已有待确认或待审核申请，请先查看或撤回原申请");
        }
        String id = UUID.randomUUID().toString();
        Instant now = clock.instant();
        db.update("INSERT INTO after_sales_request(id,user_id,order_id,order_no,order_title,amount,reason,status,expires_at,create_time,update_time) VALUES(?,?,?,?,?,?,?,'DRAFT',?,?,?)",
                id, owner, orderId, order.number, order.title, order.amount, reason,
                Timestamp.from(now.plusSeconds(600)), Timestamp.from(now), Timestamp.from(now));
        event(owner, id, "PREPARED");
        return view(owner, request(owner, id, false));
    }

    @Transactional
    public RequestView confirm(long owner, String id) {
        Request first = request(owner, id, false);
        Order order = order(owner, first.orderId, true);
        Request current = request(owner, id, true);
        if (current.status.equals("SUBMITTED")) return view(owner, current); // 重复点击和网络重试不重复登记。
        if (!current.status.equals("DRAFT")) throw error(HttpStatus.CONFLICT, "当前申请不可确认");
        if (!current.expires.isAfter(clock.instant())) throw error(HttpStatus.GONE, "确认已过期，请重新创建申请");
        eligible(order);
        if (order.amount.compareTo(current.amount) != 0)
            throw error(HttpStatus.CONFLICT, "订单金额已变化，请撤回草稿并重新核对");
        db.update("UPDATE after_sales_request SET status='SUBMITTED',submitted_at=?,update_time=? WHERE id=? AND user_id=? AND status='DRAFT'",
                Timestamp.from(clock.instant()), Timestamp.from(clock.instant()), id, owner);
        event(owner, id, "CONFIRMED");
        return view(owner, request(owner, id, false));
    }

    @Transactional
    public RequestView withdraw(long owner, String id) {
        Request first = request(owner, id, false);
        order(owner, first.orderId, true);
        Request current = request(owner, id, true);
        if (current.status.equals("WITHDRAWN")) return view(owner, current);
        if (!List.of("DRAFT", "SUBMITTED").contains(current.status))
            throw error(HttpStatus.CONFLICT, "当前申请不可撤回");
        db.update("UPDATE after_sales_request SET status='WITHDRAWN',update_time=? WHERE id=? AND user_id=?",
                Timestamp.from(clock.instant()), id, owner);
        event(owner, id, "WITHDRAWN");
        return view(owner, request(owner, id, false));
    }

    public Map<String,Object> ordersPage(long owner, int page, int size) {
        bounds(page,size);
        var rows=db.query("SELECT * FROM order_info WHERE user_id=? AND is_deleted=0 ORDER BY create_time DESC,id DESC LIMIT ? OFFSET ?",this::orderRow,owner,size,(page-1)*size);
        var records=rows.stream().map(r -> new OrderView(Long.toString(r.id),r.number,r.title,r.status,
                switch(r.status){case "0901"->"未支付";case "0902"->"已支付";case "0903"->"已取消";case "0904"->"本地模拟退款成功";default->"未知状态";},r.amount.toPlainString(),time(r.created),owner==900001)).toList();
        return Map.of("records",records,"total",db.queryForObject("SELECT COUNT(*) FROM order_info WHERE user_id=? AND is_deleted=0",Long.class,owner),"page",page,"size",size);
    }
    public Map<String,Object> requestsPage(Long owner,String status,int page,int size) {
        bounds(page,size);
        if(status!=null&&!List.of("DRAFT","SUBMITTED","APPROVED","REJECTED","WITHDRAWN","EXPIRED","REFUNDING","REFUNDED","REFUND_FAILED").contains(status))
            throw error(HttpStatus.UNPROCESSABLE_ENTITY,"申请状态不正确");
        String where=" WHERE 1=1";
        var args=new java.util.ArrayList<Object>();
        if(owner!=null){where+=" AND user_id=?";args.add(owner);}
        if("DRAFT".equals(status)){where+=" AND status='DRAFT' AND expires_at>?";args.add(Timestamp.from(clock.instant()));}
        else if("EXPIRED".equals(status)){where+=" AND (status='EXPIRED' OR (status='DRAFT' AND expires_at<=?))";args.add(Timestamp.from(clock.instant()));}
        else if(status!=null){where+=" AND status=?";args.add(status);}
        long total=db.queryForObject("SELECT COUNT(*) FROM after_sales_request"+where,Long.class,args.toArray());
        args.add(size);args.add((page-1)*size);
        var records=db.query("SELECT * FROM after_sales_request"+where+" ORDER BY create_time DESC,id DESC LIMIT ? OFFSET ?",(r,i)->view(r.getLong("user_id"),requestRow(r,i)),args.toArray());
        return Map.of("records",records,"total",total,"page",page,"size",size);
    }
    private void bounds(int page,int size) {
        if(page<1||page>10000||size<1||size>50) throw error(HttpStatus.UNPROCESSABLE_ENTITY,"分页大小为 1 至 50，页码为 1 至 10000");
    }
    public List<Map<String,Object>> events(String id) {
        return db.queryForList("SELECT event_type,actor_id,create_time FROM after_sales_event WHERE request_id=? ORDER BY id",id);
    }
    @Transactional
    public RequestView review(long actor,String id,String decision,String note) {
        if(!List.of("APPROVED","REJECTED").contains(decision)||note==null||note.strip().length()<5||note.length()>500)
            throw error(HttpStatus.UNPROCESSABLE_ENTITY,"请填写 5 至 500 字审核意见并选择通过或驳回");
        var owners=db.queryForList("SELECT user_id FROM after_sales_request WHERE id=?",id);
        if(owners.isEmpty()) throw error(HttpStatus.NOT_FOUND,"申请不存在");
        long owner=((Number)owners.get(0).get("user_id")).longValue();
        Request first=request(owner,id,false);
        Order original=order(owner,first.orderId,true);
        Request current=request(owner,id,true);
        if(current.status.equals(decision)&&note.strip().equals(current.reviewNote)) return view(owner,current);
        if(!current.status.equals("SUBMITTED")) throw error(HttpStatus.CONFLICT,"申请已处理或已撤回，请刷新状态");
        if("APPROVED".equals(decision)) {
            eligible(original);
            if(original.amount.compareTo(current.amount)!=0) throw error(HttpStatus.CONFLICT,"订单金额已变化，无法审核通过，请核对后驳回并重新申请");
        }
        db.update("UPDATE after_sales_request SET status=?,review_note=?,reviewer_id=?,reviewed_at=?,update_time=? WHERE id=? AND status='SUBMITTED'",
                decision,note.strip(),actor,Timestamp.from(clock.instant()),Timestamp.from(clock.instant()),id);
        db.update("INSERT INTO after_sales_event(request_id,user_id,actor_id,event_type,create_time) VALUES(?,?,?,?,?)",id,owner,actor,decision,Timestamp.from(clock.instant()));
        return view(owner,request(owner,id,false));
    }
}
