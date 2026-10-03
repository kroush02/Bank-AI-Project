from Adhoc_agent.models import Ticket
from Adhoc_agent.Tools.queue import LocalQueue


class RequestAgent:
    def __init__(self, queue: LocalQueue):
        self.queue = queue

    def fetch(self) -> Ticket | None:
        return self.queue.claim()
