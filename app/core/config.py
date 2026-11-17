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
