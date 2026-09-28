// AI-assisted
package com.a07.server.metadata;

import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

/** table_relationships 数据访问。 */
@Mapper
public interface TableRelationshipMapper extends BaseMapper<TableRelationshipEntity> {

    @Delete("DELETE FROM table_relationships WHERE data_source_id = #{dataSourceId}")
    int deleteByDataSourceId(@Param("dataSourceId") Long dataSourceId);
}
