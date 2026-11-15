"""Progress-aware heartbeat.

Two clocks, deliberately separate:

* ``heartbeat_at``      - proof a process is alive.
* ``lease_expires_at``  - proof work is advancing; only extended on progress.

A worker that is alive but making no progress therefore loses its lease and is
redispatched. That is the intended stalled-job detection, not a bug. Call
``progress()`` from the extraction loop whenever real work advances.
"""

from __future__ import annotations

import threading

from app import fenced


class LeaseKeeper(threading.Thread):
    """Timer-driven lease renewal.

    Renews on a wall-clock interval regardless of whether the runner is yielding
    rows. A blocking extraction call - a Last9 retry chain, a slow page - yields
    nothing, so an inline, yield-driven renewal lets the lease expire while the
    worker is perfectly healthy.

    Each tick opens its own short transaction: no session is shared with the
    runner, so there is no cross-thread session state and no long-lived
    connection. The thread exits on the first failed renewal, on any terminal
    job state (``renew_progress`` requires ``status='running'``), and on
    ``stop()``. It is a daemon, so a crashed runner cannot be kept alive by it.
    """

    daemon = True

    def __init__(self, engine, job_id: int, token: int, *, ttl: int = 60, interval: int = 15):
        super().__init__(name=f"lease-keeper-{job_id}")
        self._engine = engine
        self._job_id = job_id
        self._token = token
        self._ttl = ttl
        self._interval = interval
        self._stop = threading.Event()
        self.lost = threading.Event()

    def tick(self) -> bool:
        try:
            with self._engine.begin() as conn:
                ok = fenced.renew_progress(conn, self._job_id, self._token, self._ttl)
        except Exception:  # noqa: BLE001 - DB blip is not proof of lost ownership
            return True
        if not ok:
            self.lost.set()
            return False
        return True

    def run(self) -> None:
        while not self._stop.wait(self._interval):
            if not self.tick():
                break

    def stop(self) -> None:
        self._stop.set()


class Heartbeat(threading.Thread):
    daemon = True

    def __init__(self, engine, job_id: int, token: int, *, ttl: int = 60, interval: int = 10):
        super().__init__(name=f"heartbeat-{job_id}")
        self._engine = engine
        self._job_id = job_id
        self._token = token
        self._ttl = ttl
        self._interval = interval
        self._progress_seq = 0
        # 0, not -1: the claim itself already stamped progress, so the first
        # tick must not extend the lease unless work has actually advanced.
        self._renewed_at = 0
        self._stop = threading.Event()
        self.lost = False

    def progress(self) -> None:
        """Signal that work advanced. Only this extends the lease."""
        self._progress_seq += 1

    def tick(self) -> bool:
        """One heartbeat cycle. Returns False once the lease is lost."""
        seq = self._progress_seq
        try:
            with self._engine.begin() as conn:
                if seq > self._renewed_at:
                    if not fenced.renew_progress(conn, self._job_id, self._token, self._ttl):
                        self.lost = True
                        return False
                    self._renewed_at = seq
                else:
                    fenced.heartbeat_only(conn, self._job_id, self._token)
        except Exception:  # noqa: BLE001 - a DB blip must not kill the job; next tick retries
            return True
        return True

    def run(self) -> None:
        while not self._stop.wait(self._interval):
            if not self.tick():
                break

    def stop(self) -> None:
        self._stop.set()
