import asyncio
import hashlib
import logging
import os
from typing import List, Dict, Any, Optional
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse
from services.llm import LLMService

logger = logging.getLogger(__name__)

class MemoryService:
    def __init__(self):
        self.host = os.getenv("QDRANT_HOST", "localhost")
        self.port = int(os.getenv("QDRANT_PORT", 6333))
        self.collection_name = os.getenv("COLLECTION_NAME", "autoai_memory")
        self.client = AsyncQdrantClient(host=self.host, port=self.port)
        self.llm = LLMService()
        asyncio.create_task(self._ensure_collection())
    
    async def _ensure_collection(self):
        try:
            collections = await self.client.get_collections()
            if self.collection_name not in [c.name for c in collections.collections]:
                await self.create_collection()
                logger.info(f"Created collection '{self.collection_name}'")
        except Exception as e:
            logger.error(f"Error ensuring collection: {e}")

    async def create_collection(self):
        dummy_embed = self.llm.get_embedding("test")
        vector_size = len(dummy_embed)
        
        await self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE
            )
        )
        await self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name="source",
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True
        )
        await self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name="chunk_id",
            field_schema=models.PayloadSchemaType.INTEGER,
            wait=True
        )

    async def delete_collection(self):
        try:
            await self.client.delete_collection(collection_name=self.collection_name)
            logger.info(f"Deleted collection '{self.collection_name}'")
        except UnexpectedResponse:
            logger.info(f"Collection '{self.collection_name}' does not exist.")

    async def add_document(self, text: str, metadata: Dict[str, Any], chunk_size: int = 256) -> int:
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        if not chunks:
            return 0
        
        points = []
        for i, chunk in enumerate(chunks):
            unique_str = f"{metadata.get('source', 'unknown')}_{chunk}_{i}"
            point_id = hashlib.md5(unique_str.encode()).hexdigest()
            
            embedding = self.llm.get_embedding(chunk)
            
            payload = {
                "text": chunk,
                "source": metadata.get("source", "unknown"),
                "chunk_id": i,
                "total_chunks": len(chunks)
            }
            
            points.append(models.PointStruct(
                id=point_id,
                vector=embedding,
                payload=payload
            ))
        
        await self.client.upsert(
            collection_name=self.collection_name,
            points=points,
            wait=True
        )
        
        logger.info(f"Added {len(points)} chunks from '{metadata.get('source', 'unknown')}' to memory.")
        return len(points)

    async def search(self, query: str, limit: int = 5) -> List[models.ScoredPoint]:
        query_embed = self.llm.get_embedding(query)
        
        results = await self.client.query_points(
            collection_name=self.collection_name,
            query=query_embed,
            limit=limit,
            with_payload=True
        )
        return results.points

    async def delete_by_filename(self, filename: str) -> int:
        scroll_result = await self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="source", match=models.MatchValue(value=filename))]
            ),
            limit=1000,
            with_payload=False,
            with_vectors=False
        )
        points = scroll_result[0]
        if points:
            point_ids = [point.id for point in points]
            await self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=point_ids),
                wait=True
            )
            return len(point_ids)
        return 0

    async def get_collection_size(self) -> int:
        try:
            info = await self.client.get_collection(collection_name=self.collection_name)
            return info.points_count
        except Exception:
            return 0

    async def delete_by_filter(self, filter_condition: models.Filter) -> int:
        scroll_result = await self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=filter_condition,
            limit=1000,
            with_payload=False,
            with_vectors=False
        )
        points = scroll_result[0]
        if points:
            point_ids = [point.id for point in points]
            await self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=point_ids),
                wait=True
            )
            return len(point_ids)
        return 0

    async def update_by_source(self, source: str, new_text: str) -> int:
        deleted = await self.delete_by_filename(source)
        logger.info(f"Deleted {deleted} old chunks for source '{source}'")
        if new_text.strip():
            return await self.add_document(new_text, {"source": source})
        return 0