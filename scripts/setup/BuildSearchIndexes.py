"""Build only this project's public album and NL2SQL metadata indexes."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT

import asyncio
import argparse
import json
import re

import pymysql

from resource_scope import OWNER, SCOPE
from scoped_elasticsearch import ScopedElasticsearch
from listening.catalog import CATALOG
from search_sync import public_albums


async def build(with_vectors=False):
    cfg = json.loads((ROOT / ".runtime/vm-app-private.json").read_text(encoding="utf-8"))
    assert cfg["owner"] == OWNER
    es = ScopedElasticsearch(f"http://{cfg['host']}:9200")
    text = {"type": "text", "analyzer": "cjk"}
    await es.ensure("albums", {"id": {"type": "long"}, "albumTitle": {**text,'fields':{'keyword':{'type':'keyword','ignore_above':256}}},
        "albumIntro": text, "category3Id": {"type": "long"},'category1Id':{'type':'long'},
        'category2Id':{'type':'long'},'categoryName':{**text,'fields':{'keyword':{'type':'keyword'}}},
        'payType':{'type':'keyword'},'playCount':{'type':'long'},'createTime':{'type':'date'}})
    await es.ensure("metadata", {"kind": {"type": "keyword"}, "view": {"type": "keyword"},
        "column": {"type": "keyword"}, "text": text, "value": {"type": "keyword"}})
    metadata = []
    for view, info in CATALOG.items():
        metadata.append(("view:" + view, {"kind": "view", "view": view, "text": info["description"]}))
        for column, label in info["columns"].items():
            metadata.append((f"field:{view}:{column}", {"kind": "column", "view": view,
                "column": column, "text": f"{label} {info['description']} {column}"}))
    with pymysql.connect(host=cfg["host"], user=SCOPE.mysql_user, password=cfg["mysql_password"],
        database=SCOPE.schema("tingshu_album"), charset="utf8mb4", connect_timeout=8,
        cursorclass=pymysql.cursors.DictCursor) as db:
        with db.cursor() as cur:
            cur.execute("SELECT id,name FROM base_category3 WHERE is_deleted=0")
            for row in cur.fetchall():
                metadata.append(("value:category:" + str(row["id"]), {"kind": "value",
                    "view": "v_category_content", "column": "category_name", "value": row["name"],
                    "text": "三级分类 " + row["name"]}))
    albums = public_albums()
    await es.upsert("albums", albums)
    await es.upsert("metadata", metadata)
    await es.prune('albums',[identity for identity,_ in albums])
    await es.prune('metadata',[identity for identity,_ in metadata])
    if with_vectors:
        from listening_common import ServiceSettings
        from model_settings import active_connection
        from vector_stores import MetadataVectors
        from embedding_cache import cached_embeddings
        connection = active_connection(ServiceSettings(), 'embedding')
        semantic = [(identity, doc) for identity, doc in metadata if doc['kind'] in {'view', 'column'}]
        vectors = await cached_embeddings(connection, [doc['text'] for _, doc in semantic])
        await MetadataVectors(connection).build(semantic, vectors)
    report = {"owner": OWNER, "albums": len(albums), "metadata": len(metadata),
              "indexes": [SCOPE.es_index("albums"), SCOPE.es_index("metadata")], "qdrant": with_vectors}
    (ROOT / ".runtime/es-index-build.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-vectors', action='store_true')
    asyncio.run(build(parser.parse_args().with_vectors))
