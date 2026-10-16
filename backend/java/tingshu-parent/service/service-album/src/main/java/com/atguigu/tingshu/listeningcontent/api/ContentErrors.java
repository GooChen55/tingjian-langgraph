package com.atguigu.tingshu.listeningcontent.api;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.ResponseEntity;
import org.springframework.core.annotation.Order;
import java.util.Map;
@Order(-2147483648) @RestControllerAdvice(assignableTypes={ContentApiController.class,ContentAdminController.class})
public class ContentErrors {
 @ExceptionHandler(ResponseStatusException.class) public ResponseEntity<?> handle(ResponseStatusException e){return ResponseEntity.status(e.getStatusCode()).body(Map.of("detail",e.getReason()));}
 @ExceptionHandler({org.springframework.web.bind.MethodArgumentNotValidException.class,org.springframework.http.converter.HttpMessageNotReadableException.class})
 public ResponseEntity<?> parameters(Exception e){return ResponseEntity.unprocessableEntity().body(Map.of("detail","内容参数不正确"));}
 @ExceptionHandler(org.springframework.dao.DuplicateKeyException.class)
 public ResponseEntity<?> duplicate(Exception e){return ResponseEntity.status(409).body(Map.of("detail","请求编号已被使用，请检查原请求状态"));}
}
