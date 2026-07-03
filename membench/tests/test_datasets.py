from pathlib import Path

from membench import datasets

FIXTURES = Path(__file__).parent / "fixtures"


def test_longmemeval_loader(lme_conversations):
    convs = lme_conversations
    assert len(convs) == 3
    first = convs[0]
    assert first.benchmark == datasets.LONGMEMEVAL_S
    assert first.conv_id == "mini_1"
    assert len(first.sessions) == 2
    assert first.sessions[0].session_id == "s1"
    assert first.sessions[0].date == "2023/05/01 (Mon) 10:00"
    assert first.sessions[0].turns[0].role == "user"
    assert "guitar" in first.sessions[0].turns[0].content
    q = first.questions[0]
    assert q.category == "single-session-user"
    assert q.abstention is False
    assert q.question_date == "2023/06/01 (Thu) 10:00"


def test_longmemeval_abstention_flag(lme_conversations):
    abstention = lme_conversations[1].questions[0]
    assert abstention.question_id == "mini_2_abs"
    assert abstention.abstention is True


def test_longmemeval_subset():
    convs = datasets.load_longmemeval(FIXTURES / "mini_longmemeval.json", subset=1)
    assert len(convs) == 1
    assert convs[0].conv_id == "mini_1"


def test_locomo_loader(locomo_conversations):
    convs = locomo_conversations
    assert len(convs) == 1
    conv = convs[0]
    assert conv.benchmark == datasets.LOCOMO
    assert conv.conv_id == "mini-conv-1"
    assert conv.meta["speaker_a"] == "Caroline"
    assert len(conv.sessions) == 2
    s1 = conv.sessions[0]
    assert s1.session_id == "session_1"
    assert s1.date == "1:56 pm on 8 May, 2023"
    # speaker_a -> user, speaker_b -> assistant, names preserved in content
    assert s1.turns[0].role == "user"
    assert s1.turns[0].content.startswith("Caroline: ")
    assert s1.turns[1].role == "assistant"
    assert s1.turns[1].content.startswith("Melanie: ")
    # image-only turn keeps the blip caption
    assert "shared a photo" in s1.turns[2].content


def test_locomo_questions(locomo_conversations):
    questions = locomo_conversations[0].questions
    assert len(questions) == 6
    by_cat = {q.category_id: q for q in questions}
    assert by_cat[4].category == "single-hop"
    assert by_cat[1].category == "multi-hop"
    assert by_cat[2].category == "temporal"
    assert by_cat[3].category == "open-domain"
    # adversarial falls back to adversarial_answer and is flagged
    adversarial = by_cat[5]
    assert adversarial.category == "adversarial"
    assert adversarial.abstention is True
    assert adversarial.answer == "Not mentioned in the conversation"


def test_download_targets_defined():
    for benchmark in datasets.BENCHMARKS:
        filename, url = datasets.DOWNLOADS[benchmark]
        assert filename.endswith(".json")
        assert url.startswith("https://")
