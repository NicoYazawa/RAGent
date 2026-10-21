"""端到端冒烟 — 全链路经 MockTransport 供应商跑通 judge → embed 决策点"""
import asyncio
import json

import httpx

from app.agent import embeddings, llm
from app.config import settings
from app.providers import reset_providers
from app.providers.openai_compat import OpenAICompatEmbedder, OpenAICompatLLM


def test_full_decision_chain_with_mock_supplier():
    """One ainvoke (judge) + one astream (generate) + one embed_query, verifying the protocol loop."""
    chat_calls = {"n": 0}

    def chat_handler(request: httpx.Request) -> httpx.Response:
        chat_calls["n"] += 1
        body = json.loads(request.content)
        if body.get("stream"):
            sse = (
                'data: {"choices":[{"delta":{"content":"依据[1]"}}]}\n\n'
                'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":9,"completion_tokens":3}}\n\n'
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, text=sse)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"intent":"kb_qa","confidence":0.9,"image_note":""}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        })

    def embed_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": [0.5] * settings.resolved_embed_dims} for i in range(len(body["input"]))
        ]})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: chat_handler(r) if r.url.path.endswith("/chat/completions") else embed_handler(r)
        ),
        base_url="https://mock.local",
    )

    reset_providers()
    from app import providers
    llm_provider = OpenAICompatLLM(
        "deepseek", settings.resolved_llm_model, "https://mock.local", "sk-x",
        settings.active_llm_spec.llm_capabilities, client=client,
    )
    embed_provider = OpenAICompatEmbedder(
        "qwen", settings.resolved_embed_model, settings.resolved_embed_dims,
        "https://mock.local", "sk-x", client=client,
    )
    providers._llm_singleton = llm_provider
    providers._embed_singleton = embed_provider

    async def scenario():
        from pydantic import BaseModel

        class RouterOut(BaseModel):
            intent: str = "kb_qa"

        usage: dict = {}
        r = await llm.judge(RouterOut, "sys", "迟到怎么认定？", usage)
        assert r.intent == "kb_qa"

        msgs = llm.chat_messages("sys", [], "迟到怎么认定？")
        gen_usage: dict = {}
        text = "".join([d async for d in llm.stream_generate(msgs, gen_usage)])
        assert text == "依据[1]"

        vec = await embeddings.embed_query("迟到怎么认定？")
        assert len(vec) == settings.resolved_embed_dims

        assert usage["prompt"] == 12 and gen_usage["prompt"] == 9

    asyncio.run(scenario())
    assert chat_calls["n"] == 2
