from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str
    db_password: str
    db_name: str

    register_open: bool = False          # 默认关闭（安全默认）
    register_code: str | None = None     # 邀请码，留空则不校验

    debug: bool = False

    # ---- 登录态有效期 ----
    # token 多久不用就失效（天）。NULL 视为不过期，兼容历史 token。
    token_ttl_days: int = 30
    # 剩余有效期少于这个天数时，下一次请求自动续满。
    # 只在快过期时才写库，避免每个请求都 UPDATE 一次 token_expires_at。
    token_renew_window_days: int = 7

    # LLM（DeepSeek 兼容 OpenAI 协议）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"

    @property
    def database_url(self) -> URL:
        return URL.create(
            "mysql+aiomysql",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )


settings = Settings()
