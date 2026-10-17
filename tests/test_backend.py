"""Job queue, citation re-check and vault index - offline, on a temporary database."""
import time

from michael import db, jobs


def _wait(job_id, timeout=10):
    t = time.time()
    while time.time() - t < timeout:
        j = jobs.get(job_id)
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_jobs_run_in_order_store_events_and_survive_restart():
    db.init()
    calls = []

    def echo(params, emit, jid):
        emit({"stage": "work", "detail": f"step for {params['n']}"})
        calls.append(params["n"])
        return {"n": params["n"]}

    jobs.HANDLERS["echo"] = echo
    jobs.start()
    a = jobs.enqueue("echo", {"n": 1}, priority=5)
    j = _wait(a)
    assert j["status"] == "done" and j["result"] == {"n": 1}
    events = []
    q = jobs.subscribe(a)                       # finished job: full history, then the end marker
    while (e := q.get(timeout=2)) is not None:
        events.append(e["stage"])
    assert events[0] == "queued" and "work" in events and events[-1] == "done"


def test_cancel_a_queued_job_and_failures_are_recorded():
    db.init()
    jobs.HANDLERS["boom"] = lambda p, emit, jid: (_ for _ in ()).throw(RuntimeError("bad input"))
    jobs.start()
    j = _wait(jobs.enqueue("boom", {}))
    assert j["status"] == "error" and "bad input" in j["error"]
    jobs.HANDLERS["slow"] = lambda p, emit, jid: time.sleep(0.5)
    first = jobs.enqueue("slow", {}, priority=1)
    second = jobs.enqueue("slow", {}, priority=2)
    assert jobs.cancel(second)
    assert _wait(second)["status"] == "cancelled"
    _wait(first)


def test_citation_recheck_finds_changed_quotes(tmp_path):
    from michael.provenance import recheck_vault
    (tmp_path / "Euclid.md").write_text("# Euclid\nThe GCD of a and b is the largest number dividing both.\n", encoding="utf8")
    (tmp_path / "Answer.md").write_text(
        '---\nquestion: "x"\n---\n# x\nA.[^1] B.[^2]\n\n'
        '[^1]: "The GCD of a and b is the largest number dividing both." - [[Euclid]] · supported (entailment 0.99)\n'
        '[^2]: "A sentence that is not in the source." - [[Euclid]] · supported (entailment 0.95)\n', encoding="utf8")
    r = recheck_vault(tmp_path)
    assert r == {"checked": 2, "ok": 1, "broken": 1, "missing_source": 0, "external": 0}
    assert (tmp_path / "Michael" / "Citation check.md").exists()


def test_vault_index_full_text_search_is_incremental(tmp_path):
    from michael import vault_index
    db.init()
    (tmp_path / "Sources").mkdir()
    (tmp_path / "Sources" / "Sieve.md").write_text("# Sieve\nThe sieve of Eratosthenes finds all primes up to n.\n", encoding="utf8")
    (tmp_path / "Sources" / "Heap.md").write_text("# Heap\nA binary heap supports push and pop in log n.\n", encoding="utf8")
    assert vault_index.index_vault(tmp_path, embed=False)["indexed"] == 2
    assert vault_index.index_vault(tmp_path, embed=False)["indexed"] == 0            # nothing changed
    hits = vault_index.search("primes eratosthenes", k=3, vector=False)
    assert hits and hits[0]["title"] == "Sieve" and hits[0]["kind"] == "source"
