from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    allowed_origins: str = ""
    rate_limit_default: str = "100/minute"
    rate_limit_auth: str = "5/minute"
    redis_url: str = ""

    @property
    def origins_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
