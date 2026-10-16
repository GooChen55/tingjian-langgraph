package com.atguigu.tingshu.order.api;
import com.atguigu.tingshu.common.access.AccessService;
import com.atguigu.tingshu.common.login.GuiGuLogin;
import com.atguigu.tingshu.common.util.AuthContextHolder;
import com.atguigu.tingshu.common.result.Result;
import com.atguigu.tingshu.order.service.LocalPaymentService;
import org.springframework.context.annotation.Profile;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
@RestController @Profile({"local","vm"}) @RequestMapping("/api/order/local")
public class LocalPaymentController {
 private final LocalPaymentService service;private final AccessService access;
 public LocalPaymentController(LocalPaymentService service,AccessService access){this.service=service;this.access=access;}
 public record Checkout(@NotBlank String product,@Pattern(regexp="[a-zA-Z0-9_-]{16,64}") @NotBlank String idempotencyKey,Boolean confirmed){}
 public record Pay(@Pattern(regexp="SUCCESS|FAILED") @NotBlank String outcome,Boolean confirmed){}
 public record Refund(@Pattern(regexp="SUCCESS|FAIL_ONCE|TIMEOUT_ONCE|ALWAYS_FAIL") @NotBlank String scenario,Boolean confirmed){}
 private void confirmed(Boolean value){if(!Boolean.TRUE.equals(value))throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"请明确确认本地模拟交易，不涉及真实资金");}
 @GetMapping("/products") public Result<?> products(){return Result.ok(service.products());}
 @PostMapping("/checkout") @GuiGuLogin public Result<?> checkout(@Valid @RequestBody Checkout r){confirmed(r.confirmed);return Result.ok(service.checkout(AuthContextHolder.getUserId(),r.product,r.idempotencyKey));}
 @GetMapping("/orders/{id}") @GuiGuLogin public Result<?> detail(@PathVariable long id){return Result.ok(service.detail(AuthContextHolder.getUserId(),id));}
 @GetMapping("/orders/{id}/events") @GuiGuLogin public Result<?> events(@PathVariable long id){return Result.ok(service.events(AuthContextHolder.getUserId(),id));}
 @PostMapping("/orders/{id}/cancel") @GuiGuLogin public Result<?> cancel(@PathVariable long id){return Result.ok(service.cancel(AuthContextHolder.getUserId(),id));}
 @PostMapping("/orders/{id}/simulate") @GuiGuLogin public Result<?> simulate(@PathVariable long id,@Valid @RequestBody Pay r){confirmed(r.confirmed);return Result.ok(service.simulate(AuthContextHolder.getUserId(),id,r.outcome));}
 @PostMapping("/callback") public Result<?> callback(@RequestBody LocalPaymentService.Callback r,@RequestHeader(value="x-payment-signature",required=false) String signature){return Result.ok(service.callback(r,signature));}
 @GetMapping("/admin/refunds") public Result<?> jobs(@RequestHeader(value="admin-token",required=false) String token){access.require(token,"payments:manage");return Result.ok(service.jobs());}
 @PostMapping("/admin/refunds/{id}") public Result<?> refund(@RequestHeader(value="admin-token",required=false) String token,@PathVariable String id,@Valid @RequestBody Refund r){long actor=access.require(token,"payments:manage");confirmed(r.confirmed);return Result.ok(service.enqueue(actor,id,r.scenario));}
}
