package com.atguigu.tingshu.listeningcontent.api;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;
import com.atguigu.tingshu.common.handler.GlobalExceptionHandler;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class ContentErrorsTest {
    @Test void adminConflictKeepsHttp409InsteadOfLegacyHttp200() throws Exception {
        var controller=mock(ContentAdminController.class);
        when(controller.edit(anyLong(),any(),isNull())).thenThrow(new ResponseStatusException(HttpStatus.CONFLICT,"请求编号已用于其他修改"));
        var mvc=MockMvcBuilders.standaloneSetup(controller).setControllerAdvice(new ContentErrors(),new GlobalExceptionHandler()).build();
        mvc.perform(patch("/api/admin/content/albums/42").contentType(MediaType.APPLICATION_JSON)
            .content("{\"albumTitle\":\"示例标题\",\"published\":true,\"requestId\":\"12345678-1234-1234-1234-123456789abc\"}"))
            .andExpect(status().isConflict()).andExpect(jsonPath("$.detail").value("请求编号已用于其他修改"));
    }
    @Test void invalidAdminBodyIsHttp422() throws Exception {
        var controller=mock(ContentAdminController.class);
        var mvc=MockMvcBuilders.standaloneSetup(controller).setControllerAdvice(new ContentErrors(),new GlobalExceptionHandler()).build();
        mvc.perform(patch("/api/admin/content/albums/42").contentType(MediaType.APPLICATION_JSON).content("{\"published\":true}"))
            .andExpect(status().isUnprocessableEntity());
        verifyNoInteractions(controller);
    }
}
