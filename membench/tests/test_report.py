from membench import report
from membench.datasets import LOCOMO, LONGMEMEVAL_S

RUN_INFO = {
    "answer_model": "m",
    "judge_model": "j",
    "max_items": 20,
    "conversations": 3,
    "questions": 3,
}


def test_longmemeval_report_table():
    aggregates = {
        "context": {
            "categories": {
                "single-session-user": {"accuracy": 0.5, "n": 2},
                "abstention": {"accuracy": 1.0, "n": 1},
            },
            "overall": {"accuracy": 0.6667, "n": 3},
            "overall_excluding_abstention": {"accuracy": 0.5, "n": 2},
        },
        "search": {
            "categories": {
                "single-session-user": {"accuracy": 1.0, "n": 2},
                "abstention": {"accuracy": 0.0, "n": 1},
            },
            "overall": {"accuracy": 0.6667, "n": 3},
            "overall_excluding_abstention": {"accuracy": 1.0, "n": 2},
        },
    }
    text = report.render_report(LONGMEMEVAL_S, aggregates, RUN_INFO)
    assert "| single-session-user | 50.0% | 100.0% | 2 |" in text
    assert "| abstention | 100.0% | 0.0% | 1 |" in text
    # all paper categories present even when empty
    assert "| temporal-reasoning | — | — | 0 |" in text
    assert "**overall (excl. abstention)**" in text


def test_locomo_report_table():
    stats = {"f1": 0.5, "bleu_1": 0.25, "judge": 1.0, "n": 2}
    aggregates = {
        "context": {
            "categories": {"single-hop": stats, "adversarial": stats},
            "overall": stats,
            "overall_excluding_adversarial": stats,
        }
    }
    text = report.render_report(LOCOMO, aggregates, RUN_INFO)
    assert "| single-hop | 50.0 / 25.0 / 100.0 | 2 |" in text
    assert "| multi-hop | — | 0 |" in text
    assert "adversarial" in text
