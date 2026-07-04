import json

from conftest import FakeChat

from membench import answer, ingest


def test_ingest_writes_one_extraction_add_per_turn_pair(
    gnosis_client, gnosis_transport, cfg, lme_conversations, tmp_path
):
    conv = lme_conversations[0]  # 2 sessions x 2 turns
    written = ingest.ingest_conversation(gnosis_client, cfg, conv, log=lambda _: None)
    assert written == 4
    adds = [body for path, body in gnosis_transport.requests if path == "/v1/memories"]
    assert len(adds) == 2  # one add per user+assistant pair
    first = adds[0]
    assert first["infer"] is True
    assert first["messages"] == [
        {
            "role": "user",
            "content": "I started learning guitar last month and I practice every evening.",
        },
        {
            "role": "assistant",
            "content": "That's wonderful! Consistent practice is the key to progress.",
        },
    ]
    scope = first["scope"]
    assert scope["tenant_id"] == "bromigos"
    assert scope["user_id"] == "longmemeval_s:mini_1"
    assert scope["session_id"] == "longmemeval_s:mini_1:s1"
    assert scope["visibility"] == "private_user"
    # haystack session date carried in metadata
    assert first["metadata"]["session_date"] == "2023/05/01 (Mon) 10:00"
    assert first["metadata"]["session_id"] == "s1"


def test_ingest_odd_turn_count_sends_final_single_message_add(
    gnosis_client, gnosis_transport, cfg, lme_conversations
):
    from dataclasses import replace

    conv = lme_conversations[0]
    session = conv.sessions[0]
    odd_session = replace(session, turns=session.turns + (session.turns[0],))
    odd_conv = replace(conv, sessions=(odd_session,))
    written = ingest.ingest_conversation(gnosis_client, cfg, odd_conv, log=lambda _: None)
    assert written == 3
    adds = [body for path, body in gnosis_transport.requests if path == "/v1/memories"]
    assert [len(a["messages"]) for a in adds] == [2, 1]


def test_ingest_concurrent_sessions_writes_same_adds(
    gnosis_client, gnosis_transport, cfg, lme_conversations
):
    conv = lme_conversations[0]  # 2 sessions x 2 turns
    written = ingest.ingest_conversation(
        gnosis_client, cfg, conv, concurrency=4, log=lambda _: None
    )
    assert written == 4
    adds = [body for path, body in gnosis_transport.requests if path == "/v1/memories"]
    assert len(adds) == 2
    assert {a["scope"]["session_id"] for a in adds} == {
        "longmemeval_s:mini_1:s1",
        "longmemeval_s:mini_1:s2",
    }


def test_ingest_inline_dates_prefixes_content(
    gnosis_client, gnosis_transport, cfg, lme_conversations
):
    conv = lme_conversations[0]
    ingest.ingest_conversation(gnosis_client, cfg, conv, inline_dates=True, log=lambda _: None)
    adds = [body for path, body in gnosis_transport.requests if path == "/v1/memories"]
    assert adds[0]["messages"][0]["content"].startswith("[2023/05/01 (Mon) 10:00] ")


def test_ingest_is_resumable(gnosis_client, gnosis_transport, cfg, lme_conversations, tmp_path):
    state = tmp_path / "state.json"
    convs = lme_conversations[:2]
    summary = ingest.ingest(gnosis_client, cfg, convs, state, log=lambda _: None)
    assert summary["turns_written"] == 6  # 4 + 2
    n_first = len(gnosis_transport.requests)
    # second run skips everything
    summary = ingest.ingest(gnosis_client, cfg, convs, state, log=lambda _: None)
    assert summary["turns_written"] == 0
    assert len(gnosis_transport.requests) == n_first
    assert set(json.loads(state.read_text())["done"]) == {"mini_1", "mini_2_abs"}


def test_retrieve_search_condition_formats_dates(
    gnosis_client, gnosis_transport, cfg, lme_conversations
):
    conv = lme_conversations[0]
    text = answer.retrieve(gnosis_client, cfg, conv, conv.questions[0], "search")
    assert "- (2023/05/01 (Mon) 10:00) User started learning guitar" in text
    assert "- User likes pasta" in text
    path, body = gnosis_transport.requests[-1]
    assert path == "/v1/memories/search"
    assert body["limit"] == cfg.max_items
    assert body["query"] == conv.questions[0].question


def test_retrieve_context_condition(gnosis_client, gnosis_transport, cfg, lme_conversations):
    conv = lme_conversations[0]
    text = answer.retrieve(gnosis_client, cfg, conv, conv.questions[0], "context")
    assert "[long_term]" in text
    assert "guitar" in text
    path, body = gnosis_transport.requests[-1]
    assert path == "/v1/memory/context"
    assert body["max_items"] == cfg.max_items
    assert body["include_long_term"] is True


def test_lme_answer_prompt_uses_official_template(lme_conversations):
    conv = lme_conversations[0]
    prompt = answer.build_answer_prompt(conv, conv.questions[0], "FACTS")
    assert prompt == (
        "I will give you several facts extracted from history chats between you and a user. "
        "Please answer the question based on the relevant facts.\n\n\n"
        "History Chats:\n\nFACTS\n\n"
        "Current Date: 2023/06/01 (Thu) 10:00\n"
        "Question: What instrument did I start learning?\nAnswer:"
    )


def test_locomo_answer_prompt(locomo_conversations):
    conv = locomo_conversations[0]
    normal = conv.questions[0]
    prompt = answer.build_answer_prompt(conv, normal, "MEMORIES")
    assert "Caroline" in prompt and "Melanie" in prompt
    assert "MEMORIES" in prompt
    assert "short phrase" in prompt
    assert "No information available" in prompt
    adversarial = next(q for q in conv.questions if q.category_id == 5)
    cat5_prompt = answer.build_answer_prompt(conv, adversarial, "MEMORIES")
    assert "short phrase" not in cat5_prompt


def test_answer_all_streams_and_resumes(gnosis_client, cfg, lme_conversations, tmp_path):
    convs = lme_conversations[:1]
    out = tmp_path / "answers.jsonl"
    llm = FakeChat(["You started learning guitar."])
    results = answer.answer_all(gnosis_client, llm, cfg, convs, "search", out, log=lambda _: None)
    assert len(results) == 1
    assert results[0]["hypothesis"] == "You started learning guitar."
    assert results[0]["condition"] == "search"
    assert llm.calls[0]["model"] == "test-answerer"
    # resume: no new LLM calls
    llm2 = FakeChat([])
    results2 = answer.answer_all(gnosis_client, llm2, cfg, convs, "search", out, log=lambda _: None)
    assert len(results2) == 1
    assert llm2.calls == []
