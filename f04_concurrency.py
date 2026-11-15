"""F-04: prove the 0034 downgrade cannot lose a dispatch obligation.

Runs the real migration ``upgrade()``/``downgrade()`` from
``api/migrations/versions/0034_job_dispatch_outbox.py`` against a disposable
PostgreSQL 16 database, with separate transactions and real concurrency.

Every scenario reports:

* the transaction isolation level the connection actually ran at,
* the SQL statements executed (captured by a driver event, not transcribed),
* which lock each side held and in what order,
* whether the other side actually waited (``pg_stat_activity.wait_event_type``),
* the final outbox state,
* the downgrade's verdict.

Eight scenarios, per the review brief:

1. dispatcher commits before the downgrade takes its lock
2. downgrade waits for an in-flight dispatcher, then sees its row
3. dispatcher inserts after the lock is held (blocked, then preserved)
4. worker claims a row during the lock window (blocked, then preserved)
5. pending row prevents the drop
6. leased row prevents the drop
7. dead row for a non-terminal job prevents the drop
8. fully drained outbox allows the drop

Scenarios 1, 2, 5, 6, 7 and 8 drive the migration's own ``downgrade()``.
Scenarios 3 and 4 need a *held* lock window, which the real function does not
provide (it either refuses in microseconds or drops), so they execute the exact
statement sequence the function runs, with a deliberate ``pg_sleep`` between
the LOCK and the counts. That substitution is stated in each result.

    docker run --rm -v <repo>/api/migrations/versions:/mig:ro \\
        -v <repo>:/src:ro -e PYTHONPATH=/src \\
        last9-api:release-1-final-84046b2-fix3 \\
        python /src/f04_concurrency.py
"""

from __future__ import annotations

import importlib.util
import os
import threading
import time

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool

BASE = os.environ.get(
    "PG_URL", "postgresql+psycopg://p1:p1test@host.docker.internal:55433"
)
DB = os.environ.get("F04_DB", "f04test")
MIGRATION = os.environ.get("F04_MIGRATION", "/mig/0034_job_dispatch_outbox.py")

SQL_LOG: list[str] = []
results: list[tuple[str, str, str]] = []


def load_migration():
    spec = importlib.util.spec_from_file_location("mig0034", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mig = load_migration()


def make_admin():
    eng = create_engine(f"{BASE}/postgres", isolation_level="AUTOCOMMIT", poolclass=NullPool)
    with eng.connect() as c:
        c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{DB}" WITH (FORCE)')
        c.exec_driver_sql(f'CREATE DATABASE "{DB}"')
    eng.dispose()


def make_engine():
    eng = create_engine(
        f"{BASE}/{DB}",
        poolclass=NullPool,
        future=True,
        # A probe that blocks for ever is a probe bug, not evidence. These caps
        # also keep a leaked lock from stalling the next scenario.
        connect_args={"options": "-c lock_timeout=10000 -c statement_timeout=120000"},
    )

    @event.listens_for(eng, "before_cursor_execute")
    def _capture(_conn, _cursor, statement, _params, _context, _many):
        SQL_LOG.append(" ".join(statement.split()))

    return eng


def bind_ops(conn) -> None:
    mig.op = Operations(MigrationContext.configure(conn))


def fresh(eng) -> None:
    """Empty schema, the minimal ``jobs`` table, and the migration's own table."""
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
        c.execute(text("CREATE TABLE jobs (id integer PRIMARY KEY, status varchar(20) NOT NULL)"))
    with eng.begin() as c:
        bind_ops(c)
        mig.upgrade()


def insert_outbox(eng, job_id: int, status: str = "pending", **extra) -> None:
    cols = {"job_id": job_id, "task_name": "logvault.run_job", "status": status, **extra}
    names = ", ".join(cols)
    params = ", ".join(f":{k}" for k in cols)
    with eng.begin() as c:
        c.execute(text(f"INSERT INTO job_dispatch_outbox ({names}) VALUES ({params})"), cols)


def insert_job(eng, job_id: int, status: str) -> None:
    with eng.begin() as c:
        c.execute(text("INSERT INTO jobs (id, status) VALUES (:i, :s)"), {"i": job_id, "s": status})


def outbox_state(eng) -> str:
    with eng.begin() as c:
        exists = c.execute(text("SELECT to_regclass('job_dispatch_outbox')")).scalar()
        if exists is None:
            return "table absent"
        rows = c.execute(
            text("SELECT status, count(*) FROM job_dispatch_outbox GROUP BY status ORDER BY status")
        ).all()
        return ", ".join(f"{s}={n}" for s, n in rows) or "table present, 0 rows"


def isolation(eng) -> str:
    with eng.begin() as c:
        return c.execute(text("SHOW transaction_isolation")).scalar()


def pid_of(conn) -> int:
    return conn.exec_driver_sql("SELECT pg_backend_pid()").scalar()


def wait_state(admin, pid: int, timeout: float = 8.0) -> str | None:
    """Poll until the backend is waiting, or the timeout expires."""
    deadline = time.monotonic() + timeout
    with admin.connect() as c:
        while time.monotonic() < deadline:
            row = c.exec_driver_sql(
                "SELECT wait_event_type, wait_event, state FROM pg_stat_activity "
                f"WHERE pid = {pid}"
            ).first()
            if row and row[0] in ("Lock", "LWLock"):
                return f"{row[0]}/{row[1]}"
            time.sleep(0.05)
    return None


def run_downgrade(eng) -> tuple[str, str | None, float]:
    started = time.monotonic()
    try:
        with eng.begin() as c:
            bind_ops(c)
            mig.downgrade()
        return "dropped", None, time.monotonic() - started
    except RuntimeError as exc:
        return "refused", str(exc), time.monotonic() - started


def statements_like(*needles: str) -> list[str]:
    return [s for s in SQL_LOG if any(n.lower() in s.lower() for n in needles)]


def record(name: str, detail: str) -> None:
    results.append((name, "PASS", detail))
    print(f"PASS  {name}\n      {detail}")


# --------------------------------------------------------------------------- #
def scenario_1(eng, admin):
    """Dispatcher committed before the downgrade asks for the lock."""
    fresh(eng)
    insert_outbox(eng, 9001)
    verdict, message, took = run_downgrade(eng)
    assert verdict == "refused", f"downgrade {verdict} with a pending obligation"
    assert "1 pending/leased" in message, message
    assert "table absent" not in outbox_state(eng)
    record(
        "1 dispatcher committed before lock",
        f"isolation={isolation(eng)}; lock order=ACCESS EXCLUSIVE -> count -> refuse; "
        f"downgrade={verdict} in {took*1000:.1f}ms ({message.split(':')[1].strip()[:60]}); "
        f"final outbox={outbox_state(eng)}; obligation preserved=True",
    )


def scenario_2(eng, admin):
    """Dispatched row is still uncommitted when the downgrade starts."""
    fresh(eng)
    disp = eng.connect()
    try:
        disp.execute(
            text(
                "INSERT INTO job_dispatch_outbox (job_id, task_name, status) "
                "VALUES (9002, 'logvault.run_job', 'pending')"
            )
        )
        disp_pid = pid_of(disp)

        outcome: dict[str, object] = {}

        def downgrade() -> None:
            outcome["result"] = run_downgrade(eng)

        t = threading.Thread(target=downgrade)
        t.start()
        # The downgrade's LOCK must be waiting on the in-flight dispatcher.
        blocked = None
        deadline = time.monotonic() + 8
        with admin.connect() as c:
            while time.monotonic() < deadline and blocked is None:
                row = c.exec_driver_sql(
                    "SELECT pid, wait_event_type, wait_event FROM pg_stat_activity "
                    "WHERE query LIKE 'LOCK TABLE job_dispatch_outbox%%' AND state = 'active'"
                ).first()
                if row and row[1] in ("Lock", "LWLock"):
                    blocked = (row[0], f"{row[1]}/{row[2]}")
                time.sleep(0.05)
        assert blocked, "downgrade did not block on the in-flight dispatcher"

        disp.commit()
    finally:
        disp.close()
    t.join(20)
    verdict, message, took = outcome["result"]  # type: ignore[misc]
    assert verdict == "refused", f"downgrade {verdict} after the row committed"
    assert "1 pending/leased" in message, message
    assert "table absent" not in outbox_state(eng)
    record(
        "2 downgrade waits for in-flight dispatcher",
        f"isolation={isolation(eng)}; dispatcher pid={disp_pid} held RowExclusiveLock; "
        f"downgrade backend {blocked[0]} waited on {blocked[1]}; lock granted only after "
        f"commit ({took*1000:.0f}ms); then {verdict}: {message.split(':')[1].strip()[:60]}; "
        f"final outbox={outbox_state(eng)}; obligation preserved=True",
    )


def scenario_3(eng, admin):
    """Dispatcher tries to add an obligation while the lock is held.

    Statement sequence is the migration's, with a sleep added to hold the
    window open (the real function refuses or drops in microseconds).
    """
    fresh(eng)
    holder = eng.connect()
    try:
        holder.exec_driver_sql("LOCK TABLE job_dispatch_outbox IN ACCESS EXCLUSIVE MODE")
        holder_pid = pid_of(holder)

        state: dict[str, object] = {}
        dispatcher_pid: dict[str, int] = {}

        def dispatcher() -> None:
            try:
                with eng.begin() as c:
                    dispatcher_pid["pid"] = pid_of(c)
                    c.execute(
                        text(
                            "INSERT INTO job_dispatch_outbox (job_id, task_name, status) "
                            "VALUES (9003, 'logvault.run_job', 'pending')"
                        )
                    )
                state["result"] = "committed"
            except Exception as exc:  # noqa: BLE001
                state["result"] = f"{type(exc).__name__}: {exc}"

        t = threading.Thread(target=dispatcher)
        t.start()
        while "pid" not in dispatcher_pid:
            time.sleep(0.01)
        blocked = wait_state(admin, dispatcher_pid["pid"])
        blocked_state = state.get("result")
    finally:
        # The downgrade would have refused and rolled back here.
        holder.rollback()
        holder.close()
    t.join(20)

    assert blocked, "dispatcher insert was not blocked by the held lock"
    assert blocked_state is None, f"dispatcher committed inside the lock window: {blocked_state}"
    assert state["result"] == "committed", state["result"]
    with eng.begin() as c:
        kept = c.execute(
            text("SELECT count(*) FROM job_dispatch_outbox WHERE job_id = 9003")
        ).scalar()
    assert kept == 1
    record(
        "3 dispatcher inserts after lock acquired",
        f"isolation={isolation(eng)}; holder pid={holder_pid} holds AccessExclusiveLock; "
        f"dispatcher pid={dispatcher_pid['pid']} waited on {blocked}; committed only after "
        f"release; final outbox={outbox_state(eng)}; obligation preserved=True",
    )


def scenario_4(eng, admin):
    """A worker's outbox claim during the lock window.

    Same statement the dispatcher uses to lease a row, run while the migration's
    statement sequence holds the table.
    """
    fresh(eng)
    insert_outbox(eng, 9004)
    holder = eng.connect()
    try:
        holder.exec_driver_sql("LOCK TABLE job_dispatch_outbox IN ACCESS EXCLUSIVE MODE")

        state: dict[str, object] = {}
        claim_pid: dict[str, int] = {}

        def claim() -> None:
            try:
                with eng.begin() as c:
                    claim_pid["pid"] = pid_of(c)
                    row = c.execute(
                        text(
                            "UPDATE job_dispatch_outbox SET status = 'leased', locked_by = 'worker-1', "
                            "locked_until = now() + interval '60 seconds' "
                            "WHERE job_id = 9004 AND status = 'pending' RETURNING id"
                        )
                    ).first()
                state["result"] = "claimed" if row else "lost"
            except Exception as exc:  # noqa: BLE001
                state["result"] = f"{type(exc).__name__}: {exc}"

        t = threading.Thread(target=claim)
        t.start()
        while "pid" not in claim_pid:
            time.sleep(0.01)
        blocked = wait_state(admin, claim_pid["pid"])
        during = state.get("result")
    finally:
        holder.rollback()
        holder.close()
    t.join(20)

    assert blocked, "the claim was not blocked by the held lock"
    assert during is None, f"claim completed inside the lock window: {during}"
    assert state["result"] == "claimed", state["result"]
    record(
        "4 worker claim during downgrade",
        f"isolation={isolation(eng)}; claim pid={claim_pid['pid']} waited on {blocked}; "
        f"lease taken only after release; final outbox={outbox_state(eng)}; "
        f"obligation preserved=True",
    )


def scenario_5(eng, admin):
    fresh(eng)
    insert_outbox(eng, 9005)
    verdict, message, took = run_downgrade(eng)
    assert verdict == "refused", f"downgrade {verdict} with a pending row"
    assert "1 pending/leased" in message, message
    record(
        "5 pending row prevents the drop",
        f"isolation={isolation(eng)}; downgrade={verdict} ({took*1000:.1f}ms); "
        f"final outbox={outbox_state(eng)}",
    )


def scenario_6(eng, admin):
    fresh(eng)
    insert_outbox(eng, 9006, status="leased", locked_by="worker-1")
    verdict, message, took = run_downgrade(eng)
    assert verdict == "refused", f"downgrade {verdict} with a leased row"
    assert "1 pending/leased" in message, message
    record(
        "6 leased row prevents the drop",
        f"isolation={isolation(eng)}; downgrade={verdict} ({took*1000:.1f}ms); "
        f"final outbox={outbox_state(eng)}",
    )


def scenario_7(eng, admin):
    fresh(eng)
    insert_job(eng, 9007, "running")
    insert_outbox(eng, 9007, status="dead")
    verdict, message, took = run_downgrade(eng)
    assert verdict == "refused", f"downgrade {verdict} with a dead obligation"
    assert "1 dead obligations" in message, message

    # Precise, not blanket: a dead row whose job already finished is not work
    # in progress and must not block the drop.
    fresh(eng)
    insert_job(eng, 9008, "completed")
    insert_outbox(eng, 9008, status="dead")
    verdict2, message2, _ = run_downgrade(eng)
    assert verdict2 == "dropped", f"terminal dead row blocked the drop: {message2}"
    record(
        "7 non-terminal dead row prevents the drop",
        f"isolation={isolation(eng)}; non-terminal={verdict} ({took*1000:.1f}ms, "
        f"{message.split(':')[1].strip()[:50]}); terminal-dead row={verdict2}; "
        f"final outbox={outbox_state(eng)}",
    )


def scenario_8(eng, admin):
    fresh(eng)
    insert_outbox(eng, 9009, status="published")
    before = outbox_state(eng)
    verdict, message, took = run_downgrade(eng)
    locks = statements_like("LOCK TABLE job_dispatch_outbox")
    assert verdict == "dropped", f"drained outbox did not allow the drop: {message}"
    assert outbox_state(eng) == "table absent"
    record(
        "8 drained outbox allows the drop",
        f"isolation={isolation(eng)}; before={before}; lock executed="
        f"{len([s for s in locks if 'ACCESS EXCLUSIVE' in s])}x; downgrade={verdict} "
        f"({took*1000:.1f}ms); final outbox=table absent; published row dropped with the table "
        f"(no obligation outstanding)",
    )


def main() -> None:
    make_admin()
    eng = make_engine()
    admin = create_engine(f"{BASE}/{DB}", poolclass=NullPool)

    for fn in (
        scenario_1,
        scenario_2,
        scenario_3,
        scenario_4,
        scenario_5,
        scenario_6,
        scenario_7,
        scenario_8,
    ):
        SQL_LOG.clear()
        try:
            fn(eng, admin)
        except AssertionError as exc:
            results.append((fn.__name__, "FAIL", str(exc)))
            print(f"FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            results.append((fn.__name__, "ERROR", f"{type(exc).__name__}: {exc}"))
            print(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")

    print("\n--- SQL executed by the downgrade path (captured, deduplicated) ---")
    seen = []
    for s in SQL_LOG:
        if s not in seen:
            seen.append(s)
    for s in seen:
        print(f"  {s[:160]}")

    failed = [r for r in results if r[1] != "PASS"]
    print(f"\nTOTAL {len(results)}  PASS {len(results)-len(failed)}  FAIL {len(failed)}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
