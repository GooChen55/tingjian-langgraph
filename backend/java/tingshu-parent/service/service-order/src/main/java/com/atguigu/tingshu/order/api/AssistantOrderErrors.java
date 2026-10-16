package com.atguigu.tingshu.order.api;

import java.util.Map;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice(assignableTypes={AssistantOrderApiController.class,AdminAfterSalesController.class,LocalPaymentController.class})
public class AssistantOrderErrors {
    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<?> business(ResponseStatusException error) {
        return ResponseEntity.status(error.getStatusCode()).body(Map.of("detail", error.getReason() == null ? "业务请求失败" : error.getReason()));
    }
    @ExceptionHandler({MethodArgumentNotValidException.class, HttpMessageNotReadableException.class})
    public ResponseEntity<?> parameters(Exception error) {
        return ResponseEntity.unprocessableEntity().body(Map.of("detail", "参数不正确，请核对订单与原因"));
    }
    @ExceptionHandler(org.springframework.dao.DuplicateKeyException.class)
    public ResponseEntity<?> duplicate(Exception error){return ResponseEntity.status(409).body(Map.of("detail","交易编号已被使用，请查询原交易状态"));}
}
