// AI-assisted
package com.a07.server.auth;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import org.apache.ibatis.annotations.Mapper;

/** sys_user 数据访问（P1 仅按用户名查询，BaseMapper 已覆盖）。 */
@Mapper
public interface UserMapper extends BaseMapper<UserEntity> {
}
