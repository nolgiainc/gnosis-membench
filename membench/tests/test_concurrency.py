import json
import threading
import time

from membench.concurrency import map_streaming


def _key(item):
    return str(item)


def _done(record):
    return record["id"]


def test_preserves_input_order_with_out_of_order_completion():
    # Larger ids sleep less, so completion order is the reverse of input order.
    def work(i):
        time.sleep((10 - i) * 0.01)
        return {"id": str(i), "value": i}

    items = list(range(10))
    results = map_streaming(items, work, key_fn=_key, workers=8)
    assert [r["value"] for r in results] == items


def test_workers_1_equals_serial_and_order(tmp_path):
    calls = []

    def work(i):
        calls.append(i)
        return {"id": str(i), "value": i * i}

    items = list(range(6))
    out = tmp_path / "serial.jsonl"
    results = map_streaming(items, work, out_path=out, key_fn=_key, done=_done, workers=1)
    assert calls == items  # executed strictly in order
    assert [r["value"] for r in results] == [i * i for i in items]
    # streamed file is in submission (== input) order for the serial path
    written = [json.loads(line)["value"] for line in out.read_text().splitlines()]
    assert written == [i * i for i in items]


def test_resumable_skips_done_items(tmp_path):
    out = tmp_path / "out.jsonl"
    # pre-populate two done records (note: id "1" carries a stale value to prove
    # the resumed record is reused verbatim rather than recomputed)
    out.write_text(
        json.dumps({"id": "0", "value": "OLD0"})
        + "\n"
        + json.dumps({"id": "1", "value": "OLD1"})
        + "\n"
    )
    ran = []

    def work(i):
        ran.append(i)
        return {"id": str(i), "value": i}

    items = list(range(4))
    results = map_streaming(items, work, out_path=out, key_fn=_key, done=_done, workers=4)
    assert sorted(ran) == [2, 3]  # only the not-done items ran
    assert [r["value"] for r in results] == ["OLD0", "OLD1", 2, 3]  # order + resumed values
    # appended (not rewritten): 2 original + 2 new lines
    assert len(out.read_text().splitlines()) == 4


def test_crash_safety_streams_each_result_as_completed(tmp_path):
    out = tmp_path / "stream.jsonl"
    started = threading.Event()

    def work(i):
        if i == 0:
            # let the fast items finish and be flushed before this one returns
            started.wait(timeout=2)
        return {"id": str(i), "value": i}

    def on_result(record):
        if record["id"] != "0":
            started.set()

    # workers=2 so item 0 can block while others complete and stream to disk
    results = map_streaming(
        [0, 1, 2], work, out_path=out, key_fn=_key, done=_done, workers=2, on_result=on_result
    )
    assert {r["value"] for r in results} == {0, 1, 2}
    # every completed result was persisted
    ids = {json.loads(line)["id"] for line in out.read_text().splitlines()}
    assert ids == {"0", "1", "2"}


def test_on_result_only_for_new_records(tmp_path):
    out = tmp_path / "out.jsonl"
    out.write_text(json.dumps({"id": "0", "value": 0}) + "\n")
    seen = []
    map_streaming(
        [0, 1],
        lambda i: {"id": str(i), "value": i},
        out_path=out,
        key_fn=_key,
        done=_done,
        workers=1,
        on_result=lambda r: seen.append(r["id"]),
    )
    assert seen == ["1"]  # resumed record 0 did not fire on_result
