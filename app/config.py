from pydantic_settings import BaseSettings
from pydantic import model_validator, BeforeValidator, AnyUrl
from typing import Self, Any, Annotated

def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list) | isinstance(v, str):
        return v
    raise ValueError(v)

class Settings(BaseSettings):
    PROJECT_NAME: str = "PIPELINE"
    FRONTEND_HOST: str = "http://localhost:3000"
    BACKEND_HOST: str = "http://localhost:8000"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    # Email Settings (for notifications)
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_DEFAULT_SENDER: str | None = None
    # TODO: update type to EmailStr when sqlmodel supports it
    EMAILS_FROM_EMAIL: str | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            return self.model_copy(update={"EMAILS_FROM_NAME": self.PROJECT_NAME})
        return self
    

    # Redis Settings
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_PASSWORD: str
    REDIS_DB: int
    REDIS_URL: str


    class Config:
        case_sensitive = True
        env_file = ".env"


settings = Settings() # type: ignore