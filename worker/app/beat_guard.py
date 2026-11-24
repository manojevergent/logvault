"""Single-scheduler guard.

Celery beat has no distributed lock: two instances both fire every periodic
task, which double-dispatches jobs and double-runs the reconciler. Declaring one
replica in a Compose file is not enforcement -- a `--scale beat=2`, a stray
`celery beat` on a host, or a rolling deploy overlap all defeat it.

This process takes a Redis lock before beat starts and refreshes it for as long
as it lives. If the lock is already held, it exits non-zero so the container
fails loudly instead of becoming a second scheduler. If it dies, the lock
expires on its own.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time

import redis

from app.config import get_settings

LOCK_KEY = "logvault:beat:lock"
LOCK_TTL_SECONDS = int(os.environ.get("BEAT_GUARD_TTL", "90"))
REFRESH_SECONDS = int(os.environ.get("BEAT_GUARD_REFRESH", "30"))

# A refresh cycle that cannot confirm ownership is not the same as losing it: a
# brief Redis blip should not stop scheduling. After this many consecutive
# failures we cannot prove ownership any more, so the scheduler is stopped
# rather than allowed to run as a possible second producer.
MAX_REFRESH_FAILURES = 3


def _identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


class BeatLock:
    def __init__(self, client: redis.Redis, ttl: int = LOCK_TTL_SECONDS, refresh: int = REFRESH_SECONDS):
        self._client = client
        self._ttl = ttl
        self._refresh = refresh
        self._id = _identity()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.lost = threading.Event()
        self.lost_reason: str | None = None

    def acquire(self) -> bool:
        return bool(self._client.set(LOCK_KEY, self._id, nx=True, ex=self._ttl))

    def _mark_lost(self, reason: str) -> None:
        if not self.lost.is_set():
            self.lost_reason = reason
            self.lost.set()

    def _renew_forever(self) -> None:
        failures = 0
        while not self._stop.wait(self._refresh):
            try:
                current = self._client.get(LOCK_KEY)
                if current == self._id.encode():
                    self._client.expire(LOCK_KEY, self._ttl)
                    failures = 0
                else:
                    # Someone else owns the key (or it expired and was taken):
                    # this scheduler must stop, not race them.
                    self._mark_lost(f"lock now held by {current!r}")
                    return
            except Exception as exc:  # noqa: BLE001 - Redis may be down
                failures += 1
                if failures >= MAX_REFRESH_FAILURES:
                    self._mark_lost(f"cannot verify lock: {type(exc).__name__}")
                    return

    def start(self) -> None:
        self._thread = threading.Thread(target=self._renew_forever, daemon=True)
        self._thread.start()

    def release(self) -> None:
        self._stop.set()
        if self._client.get(LOCK_KEY) == self._id.encode():
            self._client.delete(LOCK_KEY)


def main(argv: list[str] | None = None) -> int:
    """Take the lock, then run beat as a child. Exit non-zero if it is taken."""
    argv = argv if argv is not None else sys.argv[1:]
    command = argv or ["celery", "-A", "app.celery_app.celery", "beat", "--loglevel=INFO"]

    settings = get_settings()
    client = redis.Redis.from_url(settings.celery_broker_url, socket_timeout=5)
    lock = BeatLock(client)
    if not lock.acquire():
        holder = client.get(LOCK_KEY)
        print(
            f"beat_guard: another scheduler holds {LOCK_KEY} ({holder!r}); refusing to start",
            file=sys.stderr,
        )
        return 1

    lock.start()
    print(f"beat_guard: acquired {LOCK_KEY} as {lock._id}", flush=True)

    # `docker stop` sends SIGTERM. Without this the process is killed outright,
    # the child is orphaned and the lock lingers for its full TTL -- a rolling
    # deploy would then wait 90s for the new beat to start.
    def _graceful(signum, frame):  # noqa: ANN001 - signal signature
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _graceful)
    signal.signal(signal.SIGINT, _graceful)

    child = subprocess.Popen(command)
    try:
        # Supervise, do not just wait: losing the lock must stop the scheduler.
        # TTL alone only bounds how long a *stale key* survives -- it says
        # nothing about a process that still believes it is the owner.
        while child.poll() is None:
            if lock.lost.wait(timeout=2):
                print(
                    f"beat_guard: lost the scheduler lock ({lock.lost_reason}); "
                    "stopping beat to avoid duplicate dispatch",
                    file=sys.stderr,
                    flush=True,
                )
                return 3
        return child.returncode or 0
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
