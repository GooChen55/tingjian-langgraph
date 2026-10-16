package com.atguigu.tingshu.user.api;
import com.atguigu.tingshu.common.access.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.data.redis.core.*;
import org.springframework.web.server.ResponseStatusException;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;

class AccessServiceTest {
 @Test void passwordUsesRandomSaltAndRejectsInvalidHashes(){
  String one=Passwords.hash("correct-password"),two=Passwords.hash("correct-password");
  assertNotEquals(one,two);assertTrue(Passwords.matches("correct-password",one));
  assertFalse(Passwords.matches("wrong-password",one));assertFalse(Passwords.matches("correct-password","plaintext"));
 }
 @Test void ordinaryUserCannotObtainAdminSession(){
  var db=mock(JdbcTemplate.class);var redis=mock(StringRedisTemplate.class);var access=new AccessService(db,redis);
  assertEquals(403,assertThrows(ResponseStatusException.class,()->access.adminLogin(42)).getStatusCode().value());
  verifyNoInteractions(redis);
 }
 @Test void missingAdminTokenAndUnknownSessionAreRejected(){
  var db=mock(JdbcTemplate.class);var redis=mock(StringRedisTemplate.class);var values=mock(ValueOperations.class);
  when(redis.opsForValue()).thenReturn(values);var access=new AccessService(db,redis);
  assertEquals(401,assertThrows(ResponseStatusException.class,()->access.require(null,"after_sales:review")).getStatusCode().value());
  assertEquals(401,assertThrows(ResponseStatusException.class,()->access.require("a".repeat(72),"after_sales:review")).getStatusCode().value());
 }
 @Test void authorizationReadsCurrentRolesEveryTime(){
  var db=mock(JdbcTemplate.class);var redis=mock(StringRedisTemplate.class);var values=mock(ValueOperations.class);
  when(redis.opsForValue()).thenReturn(values);when(values.get(anyString())).thenReturn("42");
  when(db.queryForList(anyString(),eq(String.class),eq(42L))).thenReturn(List.of("admin:access","after_sales:review"),List.of());
  var access=new AccessService(db,redis);assertEquals(42,access.require("a".repeat(72),"after_sales:review"));
  assertEquals(403,assertThrows(ResponseStatusException.class,()->access.require("a".repeat(72),"after_sales:review")).getStatusCode().value());
 }
 @Test void revokedAdminAccessBlocksRemainingReviewPermission(){
  var db=mock(JdbcTemplate.class);var redis=mock(StringRedisTemplate.class);var values=mock(ValueOperations.class);
  when(redis.opsForValue()).thenReturn(values);when(values.get(anyString())).thenReturn("42");
  when(db.queryForList(anyString(),eq(String.class),eq(42L))).thenReturn(List.of("after_sales:review"));
  var access=new AccessService(db,redis);
  assertEquals(403,assertThrows(ResponseStatusException.class,()->access.require("a".repeat(72),"after_sales:review")).getStatusCode().value());
 }
}
