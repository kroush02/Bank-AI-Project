from Adhoc_agent.agents.extraction_agent import ExtractionAgent
from Adhoc_agent.agents.report_agent import ReportAgent
from Adhoc_agent.agents.request_agent import RequestAgent
from Adhoc_agent.agents.sql_agent import SQLAgent
from Adhoc_agent.agents.validation_agent import ValidationAgent
from Adhoc_agent.config import Settings
from Adhoc_agent.models import ClarificationRequired, WorkflowError, WorkflowResult
from Adhoc_agent.Tools.database import check_schema
from Adhoc_agent.Tools.gemini import ModelClient
from Adhoc_agent.Tools.queue import LocalQueue


class AdhocWorkflow:
    def __init__(self, settings: Settings, client: ModelClient):
        self.settings = settings
        self.client = client
        self.queue = LocalQueue(settings.queue)
        self.request_agent = RequestAgent(self.queue)
        self.sql_agent = SQLAgent(client)
        self.validation_agent = ValidationAgent(client, settings.database)
        self.extraction_agent = ExtractionAgent(
            settings.database,
            settings.max_rows,
            settings.query_timeout,
        )
        self.report_agent = ReportAgent(settings.reports)

    def run_once(self, ticket_id: str | None = None) -> WorkflowResult | None:
        # Fail before claiming a ticket when the environment is not ready.
        check_schema(self.settings.database)
        ticket = self.request_agent.fetch(ticket_id)
        if ticket is None:
            return None
        trace = [{"agent": "request", "status": "fetched"}]
        stage = "sql"
        try:
            self.queue.progress(ticket.id, trace + [{"agent": stage, "status": "running"}])
            plan = self.sql_agent.generate(ticket)
            trace.append({"agent": stage, "status": "generated"})
            stage = "validation"
            self.queue.progress(ticket.id, trace + [{"agent": stage, "status": "running"}])
            receipt = self.validation_agent.validate(ticket, plan)
            trace.append({"agent": stage, "status": "passed"})
            stage = "extraction"
            self.queue.progress(ticket.id, trace + [{"agent": stage, "status": "running"}])
            data = self.extraction_agent.extract(receipt)
            trace.append({"agent": stage, "status": "extracted", "row_count": len(data.rows)})
            stage = "report"
            self.queue.progress(ticket.id, trace + [{"agent": stage, "status": "running"}])
            report = self.report_agent.publish(ticket, receipt, data, self.client.label, trace)
            trace.append({"agent": stage, "status": "published"})
            self.queue.finish(ticket.id, "completed", trace, report_path=str(report))
            return WorkflowResult(ticket.id, "completed", str(report))
        except Exception as exc:
            status = "needs_clarification" if isinstance(exc, ClarificationRequired) else "failed"
            error = (
                str(exc) if isinstance(exc, WorkflowError) else "Unexpected local workflow failure."
            )
            trace.append({"agent": stage, "status": status, "error": error})
            self.queue.finish(ticket.id, status, trace, error=error)
            return WorkflowResult(ticket.id, status, error=error)
        except KeyboardInterrupt:
            self.queue.finish(ticket.id, "failed", trace, error="Workflow interrupted by operator.")
            raise
