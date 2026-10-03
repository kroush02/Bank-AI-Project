import argparse
import json
import sys
from dataclasses import asdict

from Adhoc_agent.config import Settings
from Adhoc_agent.demo import DEMO_REQUEST, DemoClient
from Adhoc_agent.models import WorkflowError
from Adhoc_agent.Tools.database import create_sample_database
from Adhoc_agent.Tools.gemini import GeminiClient
from Adhoc_agent.Tools.queue import LocalQueue
from Adhoc_agent.workflows.adhoc_workflow import AdhocWorkflow


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local bank ad-hoc report agents")
    parser.add_argument("--runtime", help="Local database, queue and report directory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-demo", help="Create fictional customer/transaction data")
    submit = sub.add_parser("submit", help="Add a plain-English request to the local queue")
    submit.add_argument("request")
    sub.add_parser("tickets", help="Show ticket states and reports as JSON")
    retry = sub.add_parser("retry", help="Requeue one failed or clarification ticket")
    retry.add_argument("ticket_id")
    run = sub.add_parser("run", help="Process pending tickets using Gemini")
    run.add_argument("--max-tickets", type=int, default=1)
    sub.add_parser("demo", help="Process the fixed offline fixture, with no API calls")
    serve = sub.add_parser("serve", help="Open the local Report Studio web interface")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env(args.runtime)
        if args.command == "serve":
            from Adhoc_agent.web.server import serve

            if not 1 <= args.port <= 65535:
                raise WorkflowError("Port must be 1..65535.")
            serve(settings, args.port)
            return 0
        if args.command == "init-demo":
            create_sample_database(settings.database)
            LocalQueue(settings.queue)
            print(f"Created fictional sample database: {settings.database}")
            return 0
        if args.command == "submit":
            print(LocalQueue(settings.queue).submit(args.request))
            return 0
        if args.command == "tickets":
            print(json.dumps(LocalQueue(settings.queue).list(), indent=2, ensure_ascii=False))
            return 0
        if args.command == "retry":
            LocalQueue(settings.queue).retry(args.ticket_id)
            print(f"Requeued {args.ticket_id}")
            return 0
        if args.command == "demo":
            # Never let a fixed offline fixture consume genuine pending requests.
            demo_settings = Settings(settings.runtime / "offline-demo", "", "offline")
            if not demo_settings.database.exists():
                create_sample_database(demo_settings.database)
            queue = LocalQueue(demo_settings.queue)
            queue.submit(DEMO_REQUEST)
            result = AdhocWorkflow(demo_settings, DemoClient()).run_once()
            print(json.dumps(asdict(result), indent=2))
            return 0 if result.status == "completed" else 1
        if not 1 <= args.max_tickets <= 100:
            raise WorkflowError("--max-tickets must be 1..100.")
        client = GeminiClient(settings.api_key, settings.model)
        try:
            workflow = AdhocWorkflow(settings, client)
            exit_code = 0
            for _ in range(args.max_tickets):
                result = workflow.run_once()
                if result is None:
                    print("No pending tickets.")
                    break
                print(json.dumps(asdict(result), indent=2))
                if result.status != "completed":
                    exit_code = 1
            return exit_code
        finally:
            client.close()
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
