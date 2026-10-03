import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .models import WorkflowError


@dataclass(frozen=True)
class Settings:
    runtime: Path
    api_key: str
    model: str
    max_rows: int = 10000
    query_timeout: float = 5.0

    @property
    def database(self) -> Path:
        return self.runtime / "bank.db"

    @property
    def queue(self) -> Path:
        return self.runtime / "tickets.db"

    @property
    def reports(self) -> Path:
        return self.runtime / "reports"

    @classmethod
    def from_env(cls, runtime: str | None = None):
        # Read only this project's explicit .env, never walk parent directories.
        load_dotenv(Path.cwd() / ".env", override=False)
        try:
            max_rows = int(os.getenv("BANK_MAX_ROWS", "10000"))
            timeout = float(os.getenv("BANK_QUERY_TIMEOUT_SECONDS", "5"))
        except ValueError as exc:
            raise WorkflowError("Invalid row limit or query timeout configuration.") from exc
        if not 1 <= max_rows <= 100000 or not 0 < timeout <= 60:
            raise WorkflowError("Row limit must be 1..100000; timeout must be >0 and <=60.")
        return cls(
            runtime=Path(runtime or os.getenv("BANK_RUNTIME_DIR", "runtime")).resolve(),
            api_key=os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", ""),
            model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
            max_rows=max_rows,
            query_timeout=timeout,
        )
