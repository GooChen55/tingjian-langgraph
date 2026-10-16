package com.atguigu.tingshu.order.api;

import com.atguigu.tingshu.common.access.AccessService;
import com.atguigu.tingshu.common.result.Result;
import com.atguigu.tingshu.order.service.AssistantOrderService;
import org.springframework.web.bind.annotation.*;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;

@RestController @RequestMapping("/api/order/admin/after-sales")
public class AdminAfterSalesController {
    private final AccessService access; private final AssistantOrderService service;
    public AdminAfterSalesController(AccessService access,AssistantOrderService service){this.access=access;this.service=service;}
    public record Review(@Pattern(regexp="APPROVED|REJECTED") @NotBlank String decision,@NotBlank @Size(min=5,max=500) String note){}
    @GetMapping public Result<?> page(@RequestHeader(value="admin-token",required=false) String token,
            @RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="10") int size,@RequestParam(required=false) String status) {
        access.require(token,"after_sales:read");return Result.ok(service.requestsPage(null,status,page,size));
    }
    @PostMapping("/{id}/review") public Result<?> review(@RequestHeader(value="admin-token",required=false) String token,@PathVariable String id,@Valid @RequestBody Review req){
        long actor=access.require(token,"after_sales:review");return Result.ok(service.review(actor,id,req.decision,req.note));
    }
    @GetMapping("/{id}/events") public Result<?> events(@RequestHeader(value="admin-token",required=false) String token,@PathVariable String id){
        access.require(token,"after_sales:read");return Result.ok(service.events(id));
    }
}
