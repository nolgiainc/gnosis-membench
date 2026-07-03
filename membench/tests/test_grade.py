import pytest
from conftest import FakeChat

from membench import grade

# ---------------------------------------------------------------------------
# LongMemEval judge (official protocol)
# ---------------------------------------------------------------------------


def test_lme_standard_prompt_verbatim():
    prompt = grade.get_anscheck_prompt("single-session-user", "Q?", "A", "R")
    assert prompt == (
        "I will give you a question, a correct answer, and a response from a model. "
        "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
        "If the response is equivalent to the correct answer or contains all the intermediate "
        "steps to get the correct answer, you should also answer yes. If the response only "
        "contains a subset of the information required by the answer, answer no. "
        "\n\nQuestion: Q?\n\nCorrect Answer: A\n\nModel Response: R\n\n"
        "Is the model response correct? Answer yes or no only."
    )


def test_lme_prompt_variants():
    assert "off-by-one errors" in grade.get_anscheck_prompt("temporal-reasoning", "q", "a", "r")
    assert "updated answer" in grade.get_anscheck_prompt("knowledge-update", "q", "a", "r")
    assert "Rubric" in grade.get_anscheck_prompt("single-session-preference", "q", "a", "r")
    abstention = grade.get_anscheck_prompt("single-session-user", "q", "a", "r", abstention=True)
    assert "unanswerable" in abstention
    with pytest.raises(NotImplementedError):
        grade.get_anscheck_prompt("bogus-type", "q", "a", "r")


def test_lme_judge_protocol_and_label_parsing():
    record = {
        "question_id": "mini_1",
        "category": "single-session-user",
        "question": "What instrument did I start learning?",
        "answer": "guitar",
        "hypothesis": "You started learning the guitar.",
        "abstention": False,
    }
    judge = FakeChat(["Yes."])
    graded = grade.grade_longmemeval_record(judge, "judge-model", record)
    assert graded["correct"] is True
    # official protocol: temperature 0, max_tokens 10
    assert judge.calls[0]["temperature"] == 0.0
    assert judge.calls[0]["max_tokens"] == 10

    judge = FakeChat(["No, it is wrong."])
    assert grade.grade_longmemeval_record(judge, "m", record)["correct"] is False


def test_lme_aggregation_separates_abstention():
    graded = [
        {
            "question_id": "a",
            "category": "single-session-user",
            "abstention": False,
            "correct": True,
        },
        {
            "question_id": "b",
            "category": "single-session-user",
            "abstention": False,
            "correct": False,
        },
        {
            "question_id": "c_abs",
            "category": "single-session-user",
            "abstention": True,
            "correct": True,
        },
        {
            "question_id": "d",
            "category": "temporal-reasoning",
            "abstention": False,
            "correct": True,
        },
    ]
    agg = grade.aggregate_longmemeval(graded)
    assert agg["categories"]["single-session-user"] == {"accuracy": 0.5, "n": 2}
    assert agg["categories"]["abstention"] == {"accuracy": 1.0, "n": 1}
    assert agg["categories"]["temporal-reasoning"] == {"accuracy": 1.0, "n": 1}
    assert agg["overall"] == {"accuracy": 0.75, "n": 4}
    assert agg["overall_excluding_abstention"]["n"] == 3


# ---------------------------------------------------------------------------
# LOCOMO lexical scoring (official evaluation.py behavior)
# ---------------------------------------------------------------------------


def test_normalize_answer():
    assert grade.normalize_answer("The cat, and a dog!") == "cat dog"


def test_f1_exact_after_normalization():
    assert grade.f1_score("The Eiffel Tower!", "eiffel tower") == 1.0


def test_f1_partial_overlap():
    # stemmed tokens: {play, guitar} vs {guitar}; precision 0.5, recall 1.0 -> 2/3
    assert grade.f1_score("playing guitar", "guitar") == pytest.approx(2 / 3)


def test_f1_no_overlap():
    assert grade.f1_score("apples", "guitar") == 0.0


def test_f1_multi_hop_split():
    # gt items: alice (matched, 1.0) and charlie (unmatched, 0.0) -> mean 0.5
    assert grade.f1_multi("alice, bob", "alice, charlie") == pytest.approx(0.5)


def test_category3_gold_answer_truncated_at_semicolon():
    assert grade.locomo_gold_answer(3, "No; because Baxter sprained his paw") == "No"
    assert grade.locomo_gold_answer(4, "a; b") == "a; b"


def test_adversarial_rule():
    assert grade.locomo_adversarial_correct("There is no information available about that.")
    assert grade.locomo_adversarial_correct("That was not mentioned.")
    assert not grade.locomo_adversarial_correct("A red Toyota.")
    assert grade.score_locomo_lexical(5, "No information available", "x") == {
        "f1": 1.0,
        "bleu_1": 1.0,
    }
    assert grade.score_locomo_lexical(5, "A red Toyota", "x")["f1"] == 0.0


def test_bleu_1():
    assert grade.bleu_1("the eiffel tower", "The Eiffel Tower") == pytest.approx(1.0)
    assert grade.bleu_1("", "guitar") == 0.0
    assert 0.0 < grade.bleu_1("plays acoustic guitar", "guitar") < 1.0


def test_unknown_category_raises():
    with pytest.raises(ValueError):
        grade.score_locomo_lexical(9, "x", "y")


# ---------------------------------------------------------------------------
# LOCOMO judge
# ---------------------------------------------------------------------------


def test_parse_judge_label():
    assert grade.parse_judge_label('{"reasoning": "same fact", "label": "CORRECT"}') is True
    assert grade.parse_judge_label('{"reasoning": "different", "label": "WRONG"}') is False
    assert grade.parse_judge_label("The answer is CORRECT") is True
    assert grade.parse_judge_label("garbage") is False


def test_grade_locomo_end_to_end(locomo_conversations):
    conv = locomo_conversations[0]
    records = []
    for question in conv.questions:
        hypothesis = {
            4: "pottery",
            1: "a pottery wheel",
            2: "21 June, 2023",
            3: "No",
            5: "No information available",
        }[question.category_id]
        # two category-4 questions; give the second a wrong answer
        if question.question_id.endswith("qa_1"):
            hypothesis = "a parrot"
        records.append(
            {
                "question_id": question.question_id,
                "question": question.question,
                "answer": question.answer,
                "category": question.category,
                "category_id": question.category_id,
                "hypothesis": hypothesis,
            }
        )
    # judge is called only for categories 1-4 (5 records), not adversarial
    judge = FakeChat(['{"reasoning": "ok", "label": "CORRECT"}'] * 5)
    graded = grade.grade_locomo(judge, "judge-model", records, log=lambda _: None)
    assert len(judge.calls) == 5
    agg = grade.aggregate_locomo(graded)
    assert agg["categories"]["adversarial"] == {"f1": 1.0, "bleu_1": 1.0, "judge": 1.0, "n": 1}
    assert agg["categories"]["single-hop"]["n"] == 2
    assert agg["categories"]["single-hop"]["f1"] == pytest.approx(0.5)
    assert agg["overall_excluding_adversarial"]["n"] == 5
    assert agg["overall"]["n"] == 6
