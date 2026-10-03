from pathlib import Path

from Adhoc_agent.models import QueryResult, Ticket, ValidationReceipt
from Adhoc_agent.Tools.report_generator import publish_report


class ReportAgent:
    def __init__(self, directory: Path):
        self.directory = directory

    def publish(
        self,
        ticket: Ticket,
        receipt: ValidationReceipt,
        result: QueryResult,
        model: str,
        trace: list,
    ) -> Path:
        return publish_report(self.directory, ticket, receipt, result, model, trace)
