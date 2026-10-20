"""Real Elasticsearch regression: candidate filtering must exclude a closer foreign vector.

Opt in with RAGENT_TEST_ES_URL. Only a UUID-named test index is created and deleted.
"""
import os
import uuid

import httpx
import pytest

from app import es as es_module

ES_URL = os.environ.get("RAGENT_TEST_ES_URL", "")
pytestmark = pytest.mark.skipif(not ES_URL, reason="Set RAGENT_TEST_ES_URL for real Elasticsearch tests")


@pytest.fixture
async def isolated_es(monkeypatch):
    index = f"ragent-isolation-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(es_module, "INDEX", index)
    es = es_module.Elastic()
    await es.client.aclose()
    es.client = httpx.AsyncClient(base_url=ES_URL, timeout=15, trust_env=False)
    created = False
    try:
        response = await es.client.put(f"/{index}", json={
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"properties": {
                "kb_id": {"type": "integer"},
                "embedding": {"type": "dense_vector", "dims": 2, "index": True, "similarity": "cosine"},
            }},
        })
        response.raise_for_status()
        created = True
        for kb_id, doc_id, vector in [(1, 11, [0.0, 1.0]), (2, 22, [1.0, 0.0])]:
            response = await es.client.put(f"/{index}/_doc/{doc_id}", json={
                "kb_id": kb_id, "doc_id": doc_id, "chunk_uid": str(doc_id),
                "doc_name": "same-name", "chunk_no": 1, "content": str(kb_id), "embedding": vector,
            })
            response.raise_for_status()
        response = await es.client.post(f"/{index}/_refresh")
        response.raise_for_status()
        yield es
    finally:
        if created:
            response = await es.client.delete(f"/{index}")
            response.raise_for_status()
        await es.close()


@pytest.mark.parametrize("kb_ids, expected", [
    ([1], {11}),
    ([2], {22}),
    ([1, 2], {11, 22}),
    ([999], set()),
    (None, {11, 22}),
])
async def test_real_knn_respects_knowledge_base_scope(isolated_es, kb_ids, expected):
    hits = await isolated_es.knn_search([1.0, 0.0], kb_ids, k=2)
    assert {hit["doc_id"] for hit in hits} == expected


async def test_real_knn_filters_before_top_k_even_when_foreign_vector_is_closer(isolated_es):
    hits = await isolated_es.knn_search([1.0, 0.0], [1], k=1)
    assert [hit["doc_id"] for hit in hits] == [11]

    # Negative control: the original OR query selects the foreign document.
    response = await isolated_es.client.post(f"/{es_module.INDEX}/_search", json={
        "size": 1,
        "query": {"bool": {"filter": {"term": {"kb_id": 1}}}},
        "knn": {"field": "embedding", "query_vector": [1.0, 0.0], "k": 1, "num_candidates": 100},
    })
    response.raise_for_status()
    assert response.json()["hits"]["hits"][0]["_source"]["doc_id"] == 22


async def test_real_delete_includes_unsearched_new_chunks_and_preserves_other_kb(isolated_es):
    response = await isolated_es.client.put(f'/{es_module.INDEX}/_doc/33', json={
        'kb_id': 1, 'doc_id': 33, 'chunk_uid': '33', 'content': 'new synthetic document',
        'embedding': [0.0, 1.0],
    })
    response.raise_for_status()
    # Do not refresh here: deletion must include the immediately preceding write.
    await isolated_es.delete_by_kb(1)
    response = await isolated_es.client.post(f'/{es_module.INDEX}/_search', json={'query': {'match_all': {}}})
    response.raise_for_status()
    assert [hit['_source']['doc_id'] for hit in response.json()['hits']['hits']] == [22]
