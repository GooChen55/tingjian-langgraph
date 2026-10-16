"""Bounded knowledge turns in the project's dedicated MongoDB database."""
import hashlib
from datetime import datetime, timezone, timedelta

from pymongo import AsyncMongoClient


class KnowledgeHistory:
    def __init__(self, uri):
        if not uri:
            raise ValueError('Knowledge MongoDB connection is not configured')
        self.client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5000)
        self.collection = self.client['aillisten_dev']['knowledge_history']

    @staticmethod
    def identity(session):
        return hashlib.sha256(session.encode()).hexdigest()

    async def read(self, session):
        await self.collection.create_index('expiresAt', expireAfterSeconds=0, name='history_expiry')
        row = await self.collection.find_one({'_id': self.identity(session)})
        return row.get('turns', []) if row else []

    async def append(self, session, question, answer):
        await self.collection.update_one({'_id': self.identity(session)}, {
            '$push': {'turns': {'$each': [{'question': question[:2000], 'answer': answer[:3000]}], '$slice': -4}},
            '$set': {'updated_at': datetime.now(timezone.utc),
                     'expiresAt': datetime.now(timezone.utc) + timedelta(days=30)}}, upsert=True)

    async def close(self):
        await self.client.close()
