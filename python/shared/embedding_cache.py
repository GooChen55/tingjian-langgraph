"""Model/dimension-isolated embedding cache for metadata and retrieval queries."""
import hashlib
import json
import sqlite3

import httpx
import numpy as np

from project_paths import RUNTIME
from model_settings import embedding_payload, check_response
from request_trace import forward_trace


async def cached_embeddings(connection, texts, transport=None):
    path = RUNTIME / "auxiliary-embeddings.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    namespace = hashlib.sha256(json.dumps([connection['base_url'], connection['model'], connection['dimensions']]).encode()).hexdigest()
    ids = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
    with sqlite3.connect(path, timeout=15) as db:
        db.execute("CREATE TABLE IF NOT EXISTS vectors(namespace TEXT,id TEXT,vector BLOB,PRIMARY KEY(namespace,id))")
        cached = {}
        for identity in set(ids):
            row = db.execute("SELECT vector FROM vectors WHERE namespace=? AND id=?", (namespace, identity)).fetchone()
            if row:
                v = np.frombuffer(row[0], dtype=np.float32).copy()
                if v.shape == (connection['dimensions'],) and np.isfinite(v).all() and np.linalg.norm(v) > 0:
                    cached[identity] = v
        missing = [(identity, text) for identity, text in dict(zip(ids, texts)).items() if identity not in cached]
        async with httpx.AsyncClient(timeout=45, trust_env=False, transport=transport,
            event_hooks={'request': [forward_trace]}) as http:
            for start in range(0, len(missing), 10):
                batch = missing[start:start + 10]
                response = await http.post(connection['base_url'] + "/embeddings",
                    headers={"Authorization": "Bearer " + connection['api_key']},
                    json=embedding_payload(connection, [text for _, text in batch]))
                check_response(response)
                data = sorted(response.json()['data'], key=lambda value: value['index'])
                vectors = np.array([item['embedding'] for item in data], dtype=np.float32)
                if vectors.shape != (len(batch), connection['dimensions']) or not np.isfinite(vectors).all():
                    raise ValueError("Invalid metadata embedding shape or values")
                norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                if np.any(norms == 0):
                    raise ValueError("Zero metadata embedding")
                for (identity, _), vector in zip(batch, vectors / norms):
                    cached[identity] = vector
                    db.execute("INSERT OR REPLACE INTO vectors VALUES(?,?,?)", (namespace, identity, vector.tobytes()))
                db.commit()
    return np.stack([cached[identity] for identity in ids])
