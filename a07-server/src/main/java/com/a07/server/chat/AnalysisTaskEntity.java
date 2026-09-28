// AI-assisted
package com.a07.server.chat;

import java.time.LocalDateTime;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

/** analysis_tasks 表实体（V2）。 */
@TableName("analysis_tasks")
public class AnalysisTaskEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String sessionId;

    private String question;

    private String planJson;

    /** completed | failed */
    private String status;

    private String resultRef;

    private LocalDateTime createdAt;

    private Long durationMs;

    private Long tokensCost;

    /** 步骤列表，非表列，查询详情时装配。 */
    @TableField(exist = false)
    private java.util.List<AnalysisStepEntity> steps;

    /** 结果对象，非表列，查询详情时装配。 */
    @TableField(exist = false)
    private AnalysisResultEntity result;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getSessionId() { return sessionId; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }
    public String getQuestion() { return question; }
    public void setQuestion(String question) { this.question = question; }
    public String getPlanJson() { return planJson; }
    public void setPlanJson(String planJson) { this.planJson = planJson; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getResultRef() { return resultRef; }
    public void setResultRef(String resultRef) { this.resultRef = resultRef; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    public Long getDurationMs() { return durationMs; }
    public void setDurationMs(Long durationMs) { this.durationMs = durationMs; }
    public Long getTokensCost() { return tokensCost; }
    public void setTokensCost(Long tokensCost) { this.tokensCost = tokensCost; }
    public java.util.List<AnalysisStepEntity> getSteps() { return steps; }
    public void setSteps(java.util.List<AnalysisStepEntity> steps) { this.steps = steps; }
    public AnalysisResultEntity getResult() { return result; }
    public void setResult(AnalysisResultEntity result) { this.result = result; }
}
