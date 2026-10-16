package com.atguigu.tingshu.order.api;

import com.atguigu.tingshu.common.login.GuiGuLogin;
import com.atguigu.tingshu.common.result.Result;
import com.atguigu.tingshu.common.util.AuthContextHolder;
import com.atguigu.tingshu.order.service.AssistantOrderService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

@RestController
@RequestMapping("/api/order/assistant")
public class AssistantOrderApiController {
    private final AssistantOrderService service;
    public AssistantOrderApiController(AssistantOrderService service) { this.service = service; }
    public record Prepare(@NotBlank @Pattern(regexp="^[0-9]{1,18}$") String orderId,
                          @NotBlank @Size(min=5,max=300) String reason) {}
    public record Confirm(Boolean confirmed) {}

    @GetMapping("/orders") @GuiGuLogin
    public Result<?> orders() { return Result.ok(service.orders(AuthContextHolder.getUserId())); }
    @GetMapping("/after-sales") @GuiGuLogin
    public Result<?> requests() { return Result.ok(service.requests(AuthContextHolder.getUserId())); }
    @GetMapping("/orders/page") @GuiGuLogin
    public Result<?> ordersPage(@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="10") int size) {
        return Result.ok(service.ordersPage(AuthContextHolder.getUserId(),page,size));
    }
    @GetMapping("/after-sales/page") @GuiGuLogin
    public Result<?> requestsPage(@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="10") int size) {
        return Result.ok(service.requestsPage(AuthContextHolder.getUserId(),null,page,size));
    }
    @PostMapping("/after-sales/prepare") @GuiGuLogin
    public Result<?> prepare(@Valid @RequestBody Prepare req) {
        return Result.ok(service.prepare(AuthContextHolder.getUserId(), Long.parseLong(req.orderId), req.reason));
    }
    @PostMapping("/after-sales/{id}/confirm") @GuiGuLogin
    public Result<?> confirm(@PathVariable String id, @RequestBody Confirm req) {
        if (!Boolean.TRUE.equals(req.confirmed)) throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "必须明确确认提交");
        return Result.ok(service.confirm(AuthContextHolder.getUserId(), id));
    }
    @PostMapping("/after-sales/{id}/withdraw") @GuiGuLogin
    public Result<?> withdraw(@PathVariable String id) { return Result.ok(service.withdraw(AuthContextHolder.getUserId(), id)); }
}
