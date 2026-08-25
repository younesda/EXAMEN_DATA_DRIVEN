from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    model_root: Path = Path("models")
    api_key: str = ""
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    git_commit: str = "unknown"
    request_timeout_s: float = 30.0

    @classmethod
    def from_env(cls) -> Settings:
        origins = tuple(
            value.strip()
            for value in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
            if value.strip()
        )
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            api_host=os.getenv("API_HOST", "0.0.0.0"),
            api_port=int(os.getenv("API_PORT", "8000")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            model_root=Path(os.getenv("MODEL_ROOT", "models")),
            api_key=os.getenv("API_KEY", ""),
            cors_origins=origins,
            # Render expose RENDER_GIT_COMMIT ; GIT_COMMIT reste surchargeable.
            git_commit=(os.getenv("GIT_COMMIT")
                        or os.getenv("RENDER_GIT_COMMIT", "unknown"))[:40],
            request_timeout_s=float(os.getenv("REQUEST_TIMEOUT_S", "30")),
        )

