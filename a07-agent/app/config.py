# AI-assisted
"""引擎配置（pydantic-settings）：字段与根目录 .env.example 一一对应。

env_file 同时指向仓库根 .env 与 a07-agent/.env（后者在后、同名项优先，便于本机覆盖）；
两处文件都不存在时按默认值启动，Key 缺失由 LLMClient 调用期给出明确指引（红线 R3：
Key 只经环境变量/.env，绝不硬编码、绝不入库明文）。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

_AGENT_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_DIR.parent


class LLMProviderConfig(BaseModel):
    """单个 LLM provider 连接信息（由 Settings 派生，供 LLMClient 消费）。"""

    name: str
    base_url: str
    api_key: str = ""
    model: str


class Settings(BaseSettings):
    # ---- LLM 主力（小米 MiMo，OpenAI 兼容；docs/02 §1.3/§4）----
    llm_primary_base_url: str = "https://api.mimo.mi.com/v1"
    llm_primary_api_key: str = ""
    llm_primary_model: str = "mimo-v2.5"
    llm_light_model: str = "mimo-v2-flash"
    # ---- LLM 兜底（主力超时/限流时自动切换）----
    llm_fallback_base_url: str = "https://api.deepseek.com/v1"
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = "deepseek-chat"
    # ---- MySQL（业务库只读账号，红线 R1：引擎仅持有只读凭据）----
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_db: str = "mes_demo"
    mysql_readonly_user: str = "mes_readonly"
    mysql_readonly_password: str = ""
    # ---- Agent 引擎 ----
    agent_port: int = 8100
    sql_max_limit: int = 500
    sql_timeout_seconds: int = 20
    sandbox_timeout_seconds: int = 30

    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", _AGENT_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        # 根 .env 中属于 server/前端的变量（SERVER_PORT/JWT_*/VITE_* 等）在此忽略
        extra="ignore",
    )

    @property
    def llm_primary(self) -> LLMProviderConfig:
        return LLMProviderConfig(
            name="primary",
            base_url=self.llm_primary_base_url,
            api_key=self.llm_primary_api_key,
            model=self.llm_primary_model,
        )

    @property
    def llm_fallback(self) -> LLMProviderConfig:
        return LLMProviderConfig(
            name="fallback",
            base_url=self.llm_fallback_base_url,
            api_key=self.llm_fallback_api_key,
            model=self.llm_fallback_model,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
