// AI-assisted
package com.a07.server.metadata;

import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

/** table_metadata 数据访问。 */
@Mapper
public interface TableMetadataMapper extends BaseMapper<TableMetadataEntity> {

    @Delete("DELETE FROM table_metadata WHERE data_source_id = #{dataSourceId}")
    int deleteByDataSourceId(@Param("dataSourceId") Long dataSourceId);
}
