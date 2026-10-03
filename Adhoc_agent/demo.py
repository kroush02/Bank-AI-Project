"""One fixed offline fixture; not a replacement for natural-language generation."""

from Adhoc_agent.models import Binding, SemanticReview, SQLPlan, WorkflowError

DEMO_REQUEST = (
    "Show each customer's ID, name, and total completed transaction amount in EGP for "
    "September 2026, only customers whose total is more than 5000 EGP, highest total first."
)

DEMO_SQL = """SELECT c.customer_id, c.full_name,
       ROUND(SUM(t.amount_minor) / 100.0, 2) AS total_egp
FROM customer AS c
JOIN "transaction" AS t ON c.customer_id = t.customer_id
WHERE t.currency = :currency AND t.status = :status
  AND t.transaction_date >= :start_date AND t.transaction_date < :end_date
GROUP BY c.customer_id, c.full_name
HAVING SUM(t.amount_minor) > :minimum_minor
ORDER BY total_egp DESC"""


class DemoClient:
    label = "offline-fixture (no Gemini calls)"

    def generate(self, instruction, payload, response_type):
        if payload["request"] != DEMO_REQUEST:
            raise WorkflowError(
                "Offline demo supports only its fixed sample request. "
                "Use Gemini for your own requests."
            )
        if response_type is SemanticReview:
            return SemanticReview(
                approved=True,
                reason=(
                    "Offline fixture: expected date, EGP currency, completed status, foreign-key "
                    "join and >5000 EGP filter. Live Gemini semantic review was not performed."
                ),
            )
        return SQLPlan(
            sql=DEMO_SQL,
            parameters=[
                Binding(name="currency", kind="text", value="EGP"),
                Binding(name="status", kind="text", value="completed"),
                Binding(name="start_date", kind="text", value="2026-09-01"),
                Binding(name="end_date", kind="text", value="2026-10-01"),
                Binding(name="minimum_minor", kind="integer", value="500000"),
            ],
            explanation=(
                "Completed EGP transactions during September 2026, summed per customer. "
                "Only totals above 5000 EGP are included, ordered highest first."
            ),
            clarification="",
        )
