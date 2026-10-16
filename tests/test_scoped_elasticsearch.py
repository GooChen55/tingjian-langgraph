import asyncio
import json

import httpx
import pytest

from resource_scope import OWNER, SCOPE
from scoped_elasticsearch import ScopedElasticsearch


def test_existing_foreign_index_is_never_overwritten():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={SCOPE.es_index("albums"): {"mappings": {"_meta": {"owner": "other"}}}})
    client = ScopedElasticsearch("http://example", httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="ownership"):
        asyncio.run(client.ensure("albums", {}))
    assert [r.method for r in requests] == ["GET"]


def test_bulk_has_exact_owned_index_and_checks_per_item_errors():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("_mapping"):
            return httpx.Response(200, json={SCOPE.es_index("metadata"): {"mappings": {"_meta": {"owner": OWNER}}}})
        return httpx.Response(200, json={"errors": True})
    client = ScopedElasticsearch("http://example", httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="failed"):
        asyncio.run(client.upsert("metadata", [("metric:count", {"text": "数量"})]))
    body = [json.loads(line) for line in requests[-1].content.decode().splitlines()]
    assert body[0]["index"]["_index"] == "aillisten-dev-metadata-v1"
    assert all("*" not in r.url.path for r in requests)
