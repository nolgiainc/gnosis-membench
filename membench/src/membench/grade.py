"""Official scoring for LongMemEval and LOCOMO.

LongMemEval (LLM judge)
    ``get_anscheck_prompt`` below is copied VERBATIM from the official
    evaluation script:
    https://github.com/xiaowu0162/LongMemEval/blob/main/src/evaluation/evaluate_qa.py
    Judge protocol (also from that script): temperature=0, max_tokens=10,
    label = ``'yes' in response.lower()``. The paper's headline metric is
    per-question-type accuracy plus abstention accuracy (the ``_abs`` subset).

LOCOMO (lexical metrics + LLM judge)
    ``normalize_answer``, ``f1_score`` (Porter-stemmed), the multi-answer
    ``f1`` split, and the per-category dispatch (categories 2/3/4 -> f1_score,
    1 -> multi-answer f1, 5 -> "no information available"/"not mentioned"
    substring rule; category 3 gold answers truncated at ';') are ported
    VERBATIM in behavior from the official scorer:
    https://github.com/snap-research/locomo/blob/main/task_eval/evaluation.py
    BLEU-1 follows the mem0 paper's reporting (nltk sentence_bleu, unigram
    weights, smoothing method 1). The LLM judge ("J" score) follows the
    binary CORRECT/WRONG judge methodology popularized by the mem0
    evaluation (https://github.com/mem0ai/memory-benchmarks,
    benchmarks/locomo/prompts.py); judged on categories 1-4 only, with
    category 5 scored by the official substring rule.
"""

from __future__ import annotations

import json
import re
import string
from collections import Counter
from collections.abc import Callable
from statistics import mean
from typing import Any

from nltk.stem import PorterStemmer
from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu

# ===========================================================================
# LongMemEval — official judge prompt (verbatim from evaluate_qa.py)
# ===========================================================================


# fmt: off
def get_anscheck_prompt(task, question, answer, response, abstention=False):  # noqa: C901
    if not abstention:
        if task in ['single-session-user', 'single-session-assistant', 'multi-session']:
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            prompt = template.format(question, answer, response)
        elif task == 'temporal-reasoning':
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. In addition, do not penalize off-by-one errors for the number of days. If the question asks for the number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's response is still correct. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            prompt = template.format(question, answer, response)
        elif task == 'knowledge-update':
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response contains some previous information along with an updated answer, the response should be considered as correct as long as the updated answer is the required answer.\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            prompt = template.format(question, answer, response)
        elif task == 'single-session-preference':
            template = "I will give you a question, a rubric for desired personalized response, and a response from a model. Please answer yes if the response satisfies the desired response. Otherwise, answer no. The model does not need to reflect all the points in the rubric. The response is correct as long as it recalls and utilizes the user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            prompt = template.format(question, answer, response)
        else:
            raise NotImplementedError
    else:
        template = "I will give you an unanswerable question, an explanation, and a response from a model. Please answer yes if the model correctly identifies the question as unanswerable. The model could say that the information is incomplete, or some other information is given but the asked information is not.\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the question as unanswerable? Answer yes or no only."
        prompt = template.format(question, answer, response)
    return prompt
# fmt: on


# ``complete`` is any callable (model, messages, temperature, max_tokens) -> str,
# so tests can inject a fake and run.py can pass ChatClient.complete.
JudgeFn = Callable[..., str]


def grade_longmemeval_record(
    complete: JudgeFn, judge_model: str, record: dict[str, Any]
) -> dict[str, Any]:
    prompt = get_anscheck_prompt(
        record["category"],
        record["question"],
        record["answer"],
        record["hypothesis"],
        abstention=record.get("abstention", False),
    )
    eval_response = complete(
        judge_model,
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=10,
    ).strip()
    label = "yes" in eval_response.lower()
    return {**record, "judge_response": eval_response, "correct": label}


def grade_longmemeval(
    complete: JudgeFn,
    judge_model: str,
    records: list[dict[str, Any]],
    *,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    graded = []
    for record in records:
        result = grade_longmemeval_record(complete, judge_model, record)
        graded.append(result)
        log(f"  judged {record['question_id']}: {'correct' if result['correct'] else 'wrong'}")
    return graded


def aggregate_longmemeval(graded: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-question-type accuracy, LongMemEval-paper style.

    Abstention (_abs) questions are reported as their own row, separate from
    their nominal question_type, matching the paper's tables.
    """
    by_category: dict[str, list[bool]] = {}
    for record in graded:
        key = "abstention" if record.get("abstention") else record["category"]
        by_category.setdefault(key, []).append(bool(record["correct"]))
    categories = {
        key: {"accuracy": round(mean(values), 4), "n": len(values)}
        for key, values in by_category.items()
    }
    non_abstention = [bool(r["correct"]) for r in graded if not r.get("abstention")]
    return {
        "categories": categories,
        "overall": {
            "accuracy": round(mean([bool(r["correct"]) for r in graded]), 4) if graded else 0.0,
            "n": len(graded),
        },
        "overall_excluding_abstention": {
            "accuracy": round(mean(non_abstention), 4) if non_abstention else 0.0,
            "n": len(non_abstention),
        },
    }


# ===========================================================================
# LOCOMO — official lexical scoring (behavior-verbatim from evaluation.py)
# ===========================================================================

_ps = PorterStemmer()


def normalize_answer(s: str) -> str:
    s = s.replace(",", "")

    def remove_articles(text: str) -> str:
        return re.sub(r"\b(a|an|the|and)\b", " ", text)

    def white_space_fix(text: str) -> str:
        return " ".join(text.split())

    def remove_punc(text: str) -> str:
        exclude = set(string.punctuation)
        return "".join(ch for ch in text if ch not in exclude)

    def lower(text: str) -> str:
        return text.lower()

    return white_space_fix(remove_articles(remove_punc(lower(s))))


def f1_score(prediction: str, ground_truth: str) -> float:
    prediction_tokens = [_ps.stem(w) for w in normalize_answer(prediction).split()]
    ground_truth_tokens = [_ps.stem(w) for w in normalize_answer(ground_truth).split()]
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = 1.0 * num_same / len(prediction_tokens)
    recall = 1.0 * num_same / len(ground_truth_tokens)
    return (2 * precision * recall) / (precision + recall)


def f1_multi(prediction: str, ground_truth: str) -> float:
    """Multi-answer F1 for multi-hop (category 1): split on commas, mean of best."""
    predictions = [p.strip() for p in prediction.split(",")]
    ground_truths = [g.strip() for g in ground_truth.split(",")]
    return float(mean(max(f1_score(p, gt) for p in predictions) for gt in ground_truths))


def bleu_1(prediction: str, ground_truth: str) -> float:
    """BLEU-1 as reported in the mem0 paper (nltk, unigram weights, smoothing 1)."""
    hypothesis = normalize_answer(prediction).split()
    reference = normalize_answer(ground_truth).split()
    if not hypothesis or not reference:
        return 0.0
    return float(
        sentence_bleu(
            [reference],
            hypothesis,
            weights=(1.0, 0.0, 0.0, 0.0),
            smoothing_function=SmoothingFunction().method1,
        )
    )


def locomo_gold_answer(category_id: int, answer: str) -> str:
    """Category 3 gold answers keep only the part before ';' (official rule)."""
    if category_id == 3:
        return answer.split(";")[0].strip()
    return answer


def locomo_adversarial_correct(output: str) -> bool:
    """Official category-5 rule from evaluation.py."""
    lowered = output.lower()
    return "no information available" in lowered or "not mentioned" in lowered


def score_locomo_lexical(category_id: int, hypothesis: str, answer: str) -> dict[str, float]:
    gold = locomo_gold_answer(category_id, answer)
    if category_id == 5:
        value = 1.0 if locomo_adversarial_correct(hypothesis) else 0.0
        return {"f1": value, "bleu_1": value}
    if category_id == 1:
        return {"f1": f1_multi(hypothesis, gold), "bleu_1": bleu_1(hypothesis, gold)}
    if category_id in (2, 3, 4):
        return {"f1": f1_score(hypothesis, gold), "bleu_1": bleu_1(hypothesis, gold)}
    raise ValueError(f"unknown LOCOMO category: {category_id}")


# --- LOCOMO LLM judge (mem0-style binary CORRECT/WRONG) ---------------------

LOCOMO_JUDGE_PROMPT = """Label the generated answer as CORRECT or WRONG based on the gold answer.

Rules:
1. Paraphrases and semantically equivalent answers are CORRECT; judge meaning, not exact wording.
2. Extra detail beyond the gold answer is fine as long as the gold answer's core fact is present.
3. Dates within a small tolerance of each other (a few days) and equivalent duration phrasings are CORRECT.
4. Only mark WRONG if the generated answer contradicts the gold answer, misses it entirely, or addresses a different topic.

Question: {question}
Gold answer: {answer}
Generated answer: {response}

Return JSON with "reasoning" (one sentence) and "label" (CORRECT or WRONG). Do not include both labels."""


def parse_judge_label(response: str) -> bool:
    """Parse a CORRECT/WRONG judge response (JSON preferred, substring fallback)."""
    text = response.strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        try:
            label = str(json.loads(match.group(0)).get("label", "")).strip().upper()
            if label in ("CORRECT", "WRONG"):
                return label == "CORRECT"
        except (json.JSONDecodeError, AttributeError):
            pass
    has_correct = re.search(r"\bCORRECT\b", text)
    has_wrong = re.search(r"\bWRONG\b", text)
    return bool(has_correct and not has_wrong)


def grade_locomo(
    complete: JudgeFn,
    judge_model: str,
    records: list[dict[str, Any]],
    *,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    graded = []
    for record in records:
        category_id = int(record["category_id"])
        scores = score_locomo_lexical(category_id, record["hypothesis"], record["answer"])
        judged: bool | None = None
        if category_id != 5:
            prompt = LOCOMO_JUDGE_PROMPT.format(
                question=record["question"],
                answer=locomo_gold_answer(category_id, record["answer"]),
                response=record["hypothesis"],
            )
            judge_response = complete(
                judge_model,
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
            )
            judged = parse_judge_label(judge_response)
        else:
            judge_response = None
            judged = locomo_adversarial_correct(record["hypothesis"])
        graded.append(
            {
                **record,
                **scores,
                "judge_response": judge_response,
                "correct": judged,
            }
        )
        log(f"  scored {record['question_id']}: f1={scores['f1']:.3f} judge={judged}")
    return graded


def aggregate_locomo(graded: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, list[dict[str, Any]]] = {}
    for record in graded:
        by_category.setdefault(record["category"], []).append(record)

    def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "f1": round(mean(r["f1"] for r in records), 4),
            "bleu_1": round(mean(r["bleu_1"] for r in records), 4),
            "judge": round(mean(1.0 if r["correct"] else 0.0 for r in records), 4),
            "n": len(records),
        }

    categories = {name: summarize(records) for name, records in sorted(by_category.items())}
    # Headline J score excludes adversarial (category 5), matching mem0's methodology.
    non_adversarial = [r for r in graded if int(r["category_id"]) != 5]
    return {
        "categories": categories,
        "overall": summarize(graded) if graded else {},
        "overall_excluding_adversarial": summarize(non_adversarial) if non_adversarial else {},
    }
