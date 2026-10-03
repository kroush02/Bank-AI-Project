from pathlib import Path

from Adhoc_agent.models import QueryResult, ValidationReceipt
from Adhoc_agent.Tools.sql_excuter import execute_sql


class ExtractionAgent:
    def __init__(self, database: Path, max_rows: int = 10000, timeout: float = 5):
        self.database, self.max_rows, self.timeout = database, max_rows, timeout

    def extract(self, receipt: ValidationReceipt) -> QueryResult:
        return execute_sql(self.database, receipt.plan, self.max_rows, self.timeout)
