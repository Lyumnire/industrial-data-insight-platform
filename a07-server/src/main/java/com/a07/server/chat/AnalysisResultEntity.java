// AI-assisted
package com.a07.server.chat;

import java.time.LocalDateTime;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

/** analysis_results 表实体（V2）：标准分析结果对象 + Markdown 报告。 */
@TableName("analysis_results")
public class AnalysisResultEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long taskId;

    private String standardResultJson;

    private String reportMarkdown;

    private LocalDateTime createdAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTaskId() { return taskId; }
    public void setTaskId(Long taskId) { this.taskId = taskId; }
    public String getStandardResultJson() { return standardResultJson; }
    public void setStandardResultJson(String standardResultJson) { this.standardResultJson = standardResultJson; }
    public String getReportMarkdown() { return reportMarkdown; }
    public void setReportMarkdown(String reportMarkdown) { this.reportMarkdown = reportMarkdown; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}
