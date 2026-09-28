// AI-assisted
package com.a07.server.chat;

import java.util.List;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import com.a07.server.common.PageResult;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * S4 会话/任务只读查询服务（评分点4 可查性）。
 * GET /api/chat/sessions、GET /api/tasks、GET /api/tasks/{id}。
 */
@Service
public class SessionTaskQueryService {

    private final ChatSessionMapper sessionMapper;
    private final AnalysisTaskMapper taskMapper;
    private final AnalysisStepMapper stepMapper;
    private final AnalysisResultMapper resultMapper;
    private final ChatMessageMapper messageMapper;
    private final ObjectMapper objectMapper;

    public SessionTaskQueryService(ChatSessionMapper sessionMapper, AnalysisTaskMapper taskMapper,
                                   AnalysisStepMapper stepMapper, AnalysisResultMapper resultMapper,
                                   ChatMessageMapper messageMapper, ObjectMapper objectMapper) {
        this.sessionMapper = sessionMapper;
        this.taskMapper = taskMapper;
        this.stepMapper = stepMapper;
        this.resultMapper = resultMapper;
        this.messageMapper = messageMapper;
        this.objectMapper = objectMapper;
    }

    // ==================== 会话 ====================

    public PageResult<SessionDto> listSessions(String username, long page, long size) {
        Page<ChatSessionEntity> p = new Page<>(page, size);
        Page<ChatSessionEntity> result = sessionMapper.selectPage(p,
                new LambdaQueryWrapper<ChatSessionEntity>()
                        .eq(username != null && !username.isBlank(),
                                ChatSessionEntity::getUsername, username)
                        .orderByDesc(ChatSessionEntity::getCreatedAt));
        List<SessionDto> records = result.getRecords().stream()
                .map(e -> new SessionDto(e.getId(), e.getSessionId(), e.getTitle(),
                        e.getUsername(), e.getCreatedAt()))
                .toList();
        return PageResult.of(result.getTotal(), page, size, records);
    }

    public List<ChatMessageEntity> listSessionMessages(String sessionId) {
        return messageMapper.selectList(new LambdaQueryWrapper<ChatMessageEntity>()
                .eq(ChatMessageEntity::getSessionId, sessionId)
                .orderByAsc(ChatMessageEntity::getCreatedAt));
    }

    // ==================== 任务 ====================

    public PageResult<TaskDto> listTasks(String sessionId, String status, long page, long size) {
        Page<AnalysisTaskEntity> p = new Page<>(page, size);
        Page<AnalysisTaskEntity> result = taskMapper.selectPage(p,
                new LambdaQueryWrapper<AnalysisTaskEntity>()
                        .eq(sessionId != null && !sessionId.isBlank(),
                                AnalysisTaskEntity::getSessionId, sessionId)
                        .eq(status != null && !status.isBlank(),
                                AnalysisTaskEntity::getStatus, status)
                        .orderByDesc(AnalysisTaskEntity::getCreatedAt));
        List<TaskDto> records = result.getRecords().stream()
                .map(this::toTaskDto)
                .toList();
        return PageResult.of(result.getTotal(), page, size, records);
    }

    public TaskDetailDto getTaskDetail(Long id) {
        AnalysisTaskEntity task = taskMapper.selectById(id);
        if (task == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "任务不存在: " + id);
        }

        List<AnalysisStepEntity> steps = stepMapper.selectList(
                new LambdaQueryWrapper<AnalysisStepEntity>()
                        .eq(AnalysisStepEntity::getTaskId, id)
                        .orderByAsc(AnalysisStepEntity::getId));

        AnalysisResultEntity result = resultMapper.selectOne(
                new LambdaQueryWrapper<AnalysisResultEntity>()
                        .eq(AnalysisResultEntity::getTaskId, id)
                        .orderByDesc(AnalysisResultEntity::getId)
                        .last("LIMIT 1"));

        TaskDto taskDto = toTaskDto(task);
        List<StepDto> stepDtos = steps.stream()
                .map(s -> new StepDto(s.getStepId(), s.getName(), s.getDetail(),
                        s.getStartedAt(), s.getFinishedAt()))
                .toList();

        ResultDto resultDto = null;
        if (result != null) {
            JsonNode standardResult = null;
            try {
                if (result.getStandardResultJson() != null) {
                    standardResult = objectMapper.readTree(result.getStandardResultJson());
                }
            } catch (Exception e) {
                // 解析失败时原样返回字符串
            }
            resultDto = new ResultDto(result.getId(), result.getStandardResultJson(),
                    standardResult, result.getReportMarkdown(), result.getCreatedAt());
        }

        return new TaskDetailDto(taskDto, task.getPlanJson(), stepDtos, resultDto);
    }

    private TaskDto toTaskDto(AnalysisTaskEntity e) {
        return new TaskDto(e.getId(), e.getSessionId(), e.getQuestion(), e.getStatus(),
                e.getCreatedAt(), e.getDurationMs(), e.getTokensCost());
    }

    // ==================== DTO ====================

    public record SessionDto(Long id, String sessionId, String title,
                             String username, java.time.LocalDateTime createdAt) {
    }

    public record TaskDto(Long id, String sessionId, String question, String status,
                          java.time.LocalDateTime createdAt, Long durationMs, Long tokensCost) {
    }

    public record StepDto(String stepId, String name, String detail,
                          java.time.LocalDateTime startedAt, java.time.LocalDateTime finishedAt) {
    }

    public record ResultDto(Long id, String standardResultJson, JsonNode standardResult,
                            String reportMarkdown, java.time.LocalDateTime createdAt) {
    }

    public record TaskDetailDto(TaskDto task, String planJson,
                                List<StepDto> steps, ResultDto result) {
    }
}
