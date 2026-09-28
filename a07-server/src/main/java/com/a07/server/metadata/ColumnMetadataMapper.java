// AI-assisted
package com.a07.server.metadata;

import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

/** column_metadata 数据访问。 */
@Mapper
public interface ColumnMetadataMapper extends BaseMapper<ColumnMetadataEntity> {

    @Delete("DELETE FROM column_metadata WHERE data_source_id = #{dataSourceId}")
    int deleteByDataSourceId(@Param("dataSourceId") Long dataSourceId);
}
