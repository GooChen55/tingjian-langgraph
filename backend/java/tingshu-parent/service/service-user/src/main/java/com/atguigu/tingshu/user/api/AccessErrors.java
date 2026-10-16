package com.atguigu.tingshu.user.api;

import java.util.Map;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.dao.DuplicateKeyException;

@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice(assignableTypes={AccessApiController.class,ListeningProgressController.class})
public class AccessErrors {
    @ExceptionHandler(ResponseStatusException.class) public ResponseEntity<?> business(ResponseStatusException e) {
        return ResponseEntity.status(e.getStatusCode()).body(Map.of("detail",e.getReason()));
    }
    @ExceptionHandler({MethodArgumentNotValidException.class,HttpMessageNotReadableException.class}) public ResponseEntity<?> invalid(Exception e) {
        return ResponseEntity.unprocessableEntity().body(Map.of("detail","账号为 4 至 40 位字母数字或下划线，密码为 10 至 128 位"));
    }
    @ExceptionHandler(DuplicateKeyException.class) public ResponseEntity<?> duplicate(Exception e) {
        return ResponseEntity.status(409).body(Map.of("detail","账号名已存在"));
    }
}
