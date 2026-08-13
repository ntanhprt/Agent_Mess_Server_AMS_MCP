import logging
import threading

from . import api

logger = logging.getLogger(__name__)


class HeartbeatThread:
    def __init__(self, agent_id: str, api_key: str, interval: float = 5.0):
        self.agent_id = agent_id
        self.api_key = api_key
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                api.heartbeat(self.agent_id, self.api_key)
            except Exception as exc:
                # Never kill the loop: a transient Gateway outage should not
                # permanently take this agent offline. But do make it visible.
                logger.warning("heartbeat failed: %s", exc)
            self._stop.wait(self.interval)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
