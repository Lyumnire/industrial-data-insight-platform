// AI-assisted
package com.a07.server.chat;

import java.util.List;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.a07.server.common.ApiResult;
import com.a07.server.common.PageResult;
import com.a07.server.chat.SessionTaskQueryService.SessionDto;
import com.a07.server.chat.SessionTaskQueryService.TaskDetailDto;
import com.a07.server.chat.SessionTaskQueryService.TaskDto;

/**
 * S4 会话/任务只读查询接口（评分点4 Agent 闭环可查）。
 * 新路径 authenticated；细粒度 RBAC 记遗留。
 */
@RestController
public class SessionTaskController {

    private final SessionTaskQueryService queryService;

    public SessionTaskController(SessionTaskQueryService queryService) {
        this.queryService = queryService;
    }

    @GetMapping("/api/chat/sessions")
    public ApiResult<PageResult<SessionDto>> listSessions(
            @RequestParam(required = false) String username,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResult.ok(queryService.listSessions(username, page, size));
    }

    @GetMapping("/api/chat/sessions/{sessionId}/messages")
    public ApiResult<List<ChatMessageEntity>> listSessionMessages(@PathVariable String sessionId) {
        return ApiResult.ok(queryService.listSessionMessages(sessionId));
    }

    @GetMapping("/api/tasks")
    public ApiResult<PageResult<TaskDto>> listTasks(
            @RequestParam(required = false) String sessionId,
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResult.ok(queryService.listTasks(sessionId, status, page, size));
    }

    @GetMapping("/api/tasks/{id}")
    public ApiResult<TaskDetailDto> getTaskDetail(@PathVariable Long id) {
        return ApiResult.ok(queryService.getTaskDetail(id));
    }
}
