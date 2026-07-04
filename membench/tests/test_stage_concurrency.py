"""Parallel answer/grade stages must produce identical records to serial."""

import threading

from membench import answer, grade


class EchoChat:
    """Thread-safe fake: echoes the prompt back as the completion."""

    def __init__(self):
        self._lock = threading.Lock()
        self.calls = []

    def __call__(self, model, messages, *, temperature=0.0, max_tokens=None):
        content = messages[-1]["content"]
        with self._lock:
            self.calls.append(content)
        return content

    complete = __call__


class LabelChat:
    """Thread-safe fake judge: always returns a CORRECT verdict."""

    def __init__(self):
        self._lock = threading.Lock()
        self.calls = []

    def __call__(self, model, messages, *, temperature=0.0, max_tokens=None):
        with self._lock:
            self.calls.append(messages[-1]["content"])
        return '{"reasoning": "ok", "label": "CORRECT"}'

    complete = __call__


def test_answer_all_parallel_matches_serial(gnosis_client, cfg, lme_conversations, tmp_path):
    convs = lme_conversations
    serial = answer.answer_all(
        gnosis_client,
        EchoChat(),
        cfg,
        convs,
        "search",
        tmp_path / "serial.jsonl",
        workers=1,
        log=lambda _: None,
    )
    parallel = answer.answer_all(
        gnosis_client,
        EchoChat(),
        cfg,
        convs,
        "search",
        tmp_path / "parallel.jsonl",
        workers=8,
        log=lambda _: None,
    )
    assert parallel == serial
    # order preserved: question ids follow the conversation/question order
    expected_ids = [q.question_id for c in convs for q in c.questions]
    assert [r["question_id"] for r in parallel] == expected_ids


def test_answer_all_parallel_resumes(gnosis_client, cfg, lme_conversations, tmp_path):
    convs = lme_conversations
    out = tmp_path / "answers.jsonl"
    first = answer.answer_all(
        gnosis_client, EchoChat(), cfg, convs, "search", out, workers=8, log=lambda _: None
    )
    judge = EchoChat()
    second = answer.answer_all(
        gnosis_client, judge, cfg, convs, "search", out, workers=8, log=lambda _: None
    )
    assert second == first
    assert judge.calls == []  # everything resumed, no new LLM calls


def _locomo_records(conv):
    hyp = {
        4: "pottery",
        1: "a pottery wheel",
        2: "21 June, 2023",
        3: "No",
        5: "No information available",
    }
    return [
        {
            "question_id": q.question_id,
            "question": q.question,
            "answer": q.answer,
            "category": q.category,
            "category_id": q.category_id,
            "hypothesis": hyp[q.category_id],
        }
        for q in conv.questions
    ]


def test_grade_locomo_parallel_matches_serial(locomo_conversations):
    records = _locomo_records(locomo_conversations[0])
    serial = grade.grade_locomo(LabelChat(), "judge", records, workers=1, log=lambda _: None)
    parallel = grade.grade_locomo(LabelChat(), "judge", records, workers=8, log=lambda _: None)
    assert parallel == serial
    assert [r["question_id"] for r in parallel] == [r["question_id"] for r in records]


def test_grade_longmemeval_parallel_matches_serial():
    records = [
        {
            "question_id": f"q{i}",
            "category": "single-session-user",
            "question": f"Q{i}?",
            "answer": "guitar",
            "hypothesis": "You started learning the guitar.",
            "abstention": False,
        }
        for i in range(6)
    ]
    serial = grade.grade_longmemeval(LabelChat(), "judge", records, workers=1, log=lambda _: None)
    parallel = grade.grade_longmemeval(LabelChat(), "judge", records, workers=8, log=lambda _: None)
    assert parallel == serial
    assert [r["question_id"] for r in parallel] == [r["question_id"] for r in records]
