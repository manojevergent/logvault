"""F-13: a healthy worker must not lose its lease during a blocked call.

Runs the REAL ``run_extraction`` and the REAL ``LeaseKeeper`` against a
disposable PostgreSQL 16 database, with the extraction iterator replaced by a
controlled blocking double. The double yields no rows and never calls
``on_chunk_complete`` while it is blocked, so any renewal it gets can only come
from the keeper's own wall-clock tick — not from row delivery.

What this proves: heartbeat independence. It does NOT prove Last9 integration;
the Last9 HTTP call is replaced because no non-production credential exists.

Two scenarios:

A. healthy worker: claim (60 s lease) -> blocked 70 s -> reconciler runs twice
   during the block and must not fence it -> release -> job completes.
B. superseded token: blocked 20 s while another worker takes the lease -> the
   keeper sees the token change, reports loss, and the runner refuses to
   publish.

    docker run --rm -v <repo>:/src:ro -e PYTHONPATH=/src \\
        -e DATABASE_URL=postgresql+psycopg://... \\
        last9-worker:release-1-final-84046b2-fix3 \\
        python /src/f13_blocked_extraction.py
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from datetime import UTC, datetime

os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="f13-store-"))
from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("LAST9_ENCRYPTION_KEY", Fernet.generate_key().decode())

import sqlalchemy as sa  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import crypto, db, reconciler, runner  # noqa: E402
from app.last9 import LogRow  # noqa: E402

BLOCK_SECONDS = 70.0
TTL = 60
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, "PASS" if ok else "FAIL", detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}\n      {detail}")
    if not ok:
        raise AssertionError(f"{name}: {detail}")


def seed(job_id: int) -> None:
    with db.engine().begin() as conn:
        if db.load(conn, db.last9_credentials, 1) is None:
            conn.execute(
                db.last9_credentials.insert().values(
                    id=1,
                    label="f13",
                    org_slug="evergentapse1",
                    encrypted_refresh_token=crypto.encrypt("rt-WXYZ"),
                    refresh_token_last4="WXYZ",
                    encrypted_access_token=None,
                    access_token_expires_at=None,
                )
            )
        if db.load(conn, db.index_targets, 1) is None:
            conn.execute(
                db.index_targets.insert().values(
                    id=1,
                    region_code="ap-southeast-1",
                    full_index_string="physical_index:UMServices",
                )
            )
        conn.execute(
            db.jobs.insert().values(
                id=job_id,
                status="queued",
                region_code="ap-southeast-1",
                index_target_id=1,
                credential_id=1,
                start_epoch=0,
                end_epoch=7200,
                chunk_hours=1,
                id_batch_size=100,
                filter_spec={"phrases": ["GetEntitlements"], "ids": []},
                rows_written=0,
                total_chunks=0,
                completed_chunks=0,
                lease_token=0,
                completion_state="unknown",
                gap_count=0,
                checkpoint_version=1,
            )
        )


def row(job_id: int) -> dict:
    with db.engine().begin() as conn:
        return dict(conn.execute(db.jobs.select().where(db.jobs.c.id == job_id)).mappings().one())


def events(job_id: int) -> list[str]:
    with db.engine().begin() as conn:
        return [
            r["message"]
            for r in conn.execute(
                db.job_events.select().where(db.job_events.c.job_id == job_id)
            ).mappings()
        ]


def keeper_alive(job_id: int) -> bool:
    return any(t.name == f"lease-keeper-{job_id}" and t.is_alive() for t in threading.enumerate())


class BlockingExtraction:
    """A single call that yields nothing until released."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.blocked_for = 0.0

    def __call__(self, client, spec, *, checkpoint=None, on_chunk_complete=None, **kw):
        self.entered.set()
        started = time.monotonic()
        assert self.release.wait(180), "test never released the blocked call"
        self.blocked_for = time.monotonic() - started
        yield LogRow("1", "blocked-then-released", "")


def scenario_a() -> None:
    seed(1)
    block = BlockingExtraction()
    runner.iter_extraction = block

    claimed_at = datetime.now(UTC)
    t = threading.Thread(target=runner.run_extraction, args=(1,), name="runner-a")
    t.start()
    assert block.entered.wait(10), "runner never entered the extraction call"

    first = row(1)
    lease_at_claim = first["lease_expires_at"]
    check(
        "A: claimed with a 60 s lease",
        first["status"] == "running" and first["lease_token"] == 1,
        f"status={first['status']} token={first['lease_token']} "
        f"owner={first['owner_id']} lease_in={(lease_at_claim - claimed_at).total_seconds():.1f}s",
    )

    # Let the block run past the TTL, with the reconciler watching.
    t0 = time.monotonic()

    def since() -> float:
        return time.monotonic() - t0

    time.sleep(max(0.0, 30 - since()))
    stats_mid = reconciler.reconcile_once(db.engine())
    mid = row(1)
    check(
        "A: reconciler at ~30 s does not fence a blocked healthy worker",
        stats_mid["expired"] == 0 and mid["owner_id"] is not None,
        f"reconcile={stats_mid} owner={mid['owner_id']} status={mid['status']} "
        f"blocked_for={since():.0f}s",
    )

    # Past the original 60 s expiry: only the keeper can have renewed here.
    time.sleep(max(0.0, 70 - since()))
    stats_late = reconciler.reconcile_once(db.engine())
    late = row(1)
    now = datetime.now(UTC)
    remaining = (late["lease_expires_at"] - now).total_seconds()
    check(
        "A: lease still owned and unexpired after 70 s with zero rows delivered",
        stats_late["expired"] == 0
        and late["status"] == "running"
        and late["owner_id"] == first["owner_id"]
        and remaining > 0
        and late["lease_expires_at"] > lease_at_claim,
        f"reconcile={stats_late} status={late['status']} owner={late['owner_id']} "
        f"token={late['lease_token']} lease_expires_at={late['lease_expires_at']} "
        f"(+{remaining:.0f}s from now, claim was {lease_at_claim})",
    )

    block.release.set()
    t.join(90)
    job = row(1)
    check(
        "A: runner completes after the call is released",
        not t.is_alive() and job["status"] == "completed",
        f"actual_blocked={block.blocked_for:.1f}s status={job['status']} "
        f"rows_written={job['rows_written']} finished_at={job['finished_at']}",
    )
    check(
        "A: keeper shuts down after the job turns terminal",
        _wait_gone(1, 30),
        f"thread lease-keeper-1 alive={keeper_alive(1)}",
    )
    check(
        "A: no failure or fencing event was written",
        not any(
            e.startswith(("Failed", "Publication refused", "Lease expired"))
            for e in events(1)
        ),
        f"events={[e[:60] for e in events(1)]}",
    )


def scenario_b() -> None:
    """Superseded token while blocked: keeper reports loss, runner cannot publish."""
    seed(2)
    block = BlockingExtraction()
    runner.iter_extraction = block

    t = threading.Thread(target=runner.run_extraction, args=(2,), name="runner-b")
    t.start()
    assert block.entered.wait(10), "runner never entered the extraction call"
    owned = row(2)
    check(
        "B: second job claimed",
        owned["status"] == "running" and owned["owner_id"].startswith("worker:"),
        f"owner={owned['owner_id']} token={owned['lease_token']}",
    )

    time.sleep(5)
    superseded_at = time.monotonic()
    with db.engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE jobs SET lease_token = lease_token + 1, owner_id = 'intruder', "
                "lease_expires_at = now() + interval '120 seconds' WHERE id = 2"
            )
        )
    # The keeper ticks every 15 s; give it two ticks from the block's start.
    time.sleep(max(0.0, 25 - (time.monotonic() - (superseded_at - 5))))
    check(
        "B: keeper stops itself when the token is superseded",
        not keeper_alive(2),
        f"thread lease-keeper-2 alive={keeper_alive(2)} "
        f"lease_token_now={row(2)['lease_token']}",
    )

    block.release.set()
    t.join(90)
    after = row(2)
    check(
        "B: superseded runner cannot publish or fail the new owner's job",
        not t.is_alive() and after["owner_id"] == "intruder" and after["status"] == "running",
        f"actual_blocked={block.blocked_for:.1f}s status={after['status']} "
        f"owner={after['owner_id']} token={after['lease_token']} "
        f"finished_at={after['finished_at']}",
    )


def _wait_gone(job_id: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not keeper_alive(job_id):
            return True
        time.sleep(0.5)
    return False


def main() -> None:
    db.metadata.drop_all(db.engine())
    db.metadata.create_all(db.engine())
    started = time.monotonic()
    try:
        scenario_a()
        scenario_b()
    finally:
        failed = [r for r in results if r[1] != "PASS"]
        print(
            f"\nTOTAL {len(results)}  PASS {len(results)-len(failed)}  FAIL {len(failed)}  "
            f"wall={time.monotonic()-started:.1f}s"
        )
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
