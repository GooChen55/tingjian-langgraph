package com.atguigu.tingshu.common.access;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.slf4j.*;
import java.io.IOException;
import java.util.UUID;
@Component @Profile("local")
public class RequestTraceFilter extends OncePerRequestFilter {
 private static final Logger log=LoggerFactory.getLogger(RequestTraceFilter.class);
 @Override protected void doFilterInternal(HttpServletRequest req,HttpServletResponse res,FilterChain chain)throws ServletException,IOException {
  String id=req.getHeader("x-request-id");if(id==null||!id.matches("[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"))id=UUID.randomUUID().toString();
  long start=System.nanoTime();res.setHeader("x-request-id",id);MDC.put("request_id",id);
  try{chain.doFilter(req,res);}finally{
   String route=req.getRequestURI().replaceAll("/[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}","/{id}").replaceAll("/\\d+","/{id}");
   log.info("request_id={} method={} route={} status={} duration_ms={}",id,req.getMethod(),route,res.getStatus(),(System.nanoTime()-start)/1000000);MDC.remove("request_id");
  }
 }
}
