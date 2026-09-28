// AI-assisted
package com.a07.server.chat;

import java.time.LocalDateTime;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

/** analysis_steps 表实体（V2）。 */
@TableName("analysis_steps")
public class AnalysisStepEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long taskId;

    private String stepId;

    private String name;

    private String detail;

    private LocalDateTime startedAt;

    private LocalDateTime finishedAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTaskId() { return taskId; }
    public void setTaskId(Long taskId) { this.taskId = taskId; }
    public String getStepId() { return stepId; }
    public void setStepId(String stepId) { this.stepId = stepId; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getDetail() { return detail; }
    public void setDetail(String detail) { this.detail = detail; }
    public LocalDateTime getStartedAt() { return startedAt; }
    public void setStartedAt(LocalDateTime startedAt) { this.startedAt = startedAt; }
    public LocalDateTime getFinishedAt() { return finishedAt; }
    public void setFinishedAt(LocalDateTime finishedAt) { this.finishedAt = finishedAt; }
}
