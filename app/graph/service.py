"""Knowledge graph build + graph-augmented retrieval.

Graph model (all nodes carry tenant_id — Neo4j Community has no RLS, so every
query filters on it explicitly):

    (Chunk {chunk_id, tenant_id, document_id, chunk_index})
        -[:PART_OF]->  (Document {document_id, tenant_id, title, doc_type})
        -[:MENTIONS]-> (Entity {key, tenant_id, name, norm, type})

Entity identity is `key = "{tenant_id}|{norm}"` — a single-property uniqueness
constraint (composite node keys are Enterprise-only). Co-occurrence is not
materialized as edges: it is derived at query time via Chunk bridges, which
stays correct as documents are re-ingested.
"""
import uuid
from dataclasses import dataclass

from neo4j import AsyncDriver, Driver

from app.core.config import settings
from app.graph.extraction import Entity, normalize

CONSTRAINTS = [
    "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.key IS UNIQUE",
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
    "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.document_id IS UNIQUE",
]


@dataclass
class ChunkEntities:
    chunk_id: uuid.UUID
    chunk_index: int
    entities: list[Entity]


class GraphWriter:
    """Sync (Celery worker). rebuild_document is idempotent: deletes the
    document's Chunk nodes first, so task retries converge instead of leaving
    stale chunks from a previous ingest."""

    def __init__(self, driver: Driver) -> None:
        self.driver = driver

    def ensure_constraints(self) -> None:
        with self.driver.session() as session:
            for statement in CONSTRAINTS:
                session.run(statement)

    def rebuild_document(
        self,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        title: str,
        doc_type: str,
        chunks: list[ChunkEntities],
    ) -> int:
        tid = str(tenant_id)
        doc_id = str(document_id)
        chunk_rows = [
            {"chunk_id": str(c.chunk_id), "chunk_index": c.chunk_index} for c in chunks
        ]
        mention_rows = [
            {
                "chunk_id": str(c.chunk_id),
                "key": f"{tid}|{normalize(e.name)}",
                "name": e.name,
                "norm": normalize(e.name),
                "type": e.type.value,
            }
            for c in chunks
            for e in c.entities
        ]

        with self.driver.session() as session:
            session.execute_write(
                self._rebuild_tx,
                tid=tid,
                doc_id=doc_id,
                title=title,
                doc_type=doc_type,
                chunk_rows=chunk_rows,
                mention_rows=mention_rows,
            )
        return len(mention_rows)

    @staticmethod
    def _rebuild_tx(tx, *, tid, doc_id, title, doc_type, chunk_rows, mention_rows) -> None:
        tx.run(
            "MATCH (c:Chunk {tenant_id: $tid, document_id: $doc_id}) DETACH DELETE c",
            tid=tid, doc_id=doc_id,
        )
        tx.run(
            "MERGE (d:Document {document_id: $doc_id}) "
            "SET d.tenant_id = $tid, d.title = $title, d.doc_type = $doc_type",
            tid=tid, doc_id=doc_id, title=title, doc_type=doc_type,
        )
        tx.run(
            "UNWIND $rows AS row "
            "MATCH (d:Document {document_id: $doc_id}) "
            "MERGE (c:Chunk {chunk_id: row.chunk_id}) "
            "SET c.tenant_id = $tid, c.document_id = $doc_id, c.chunk_index = row.chunk_index "
            "MERGE (c)-[:PART_OF]->(d)",
            rows=chunk_rows, tid=tid, doc_id=doc_id,
        )
        tx.run(
            "UNWIND $rows AS row "
            "MATCH (c:Chunk {chunk_id: row.chunk_id}) "
            "MERGE (e:Entity {key: row.key}) "
            "ON CREATE SET e.tenant_id = $tid, e.name = row.name, "
            "              e.norm = row.norm, e.type = row.type "
            "MERGE (c)-[:MENTIONS]->(e)",
            rows=mention_rows, tid=tid,
        )


class GraphSearcher:
    """Async (API path). Ranks chunks by entity evidence:
    direct mention of a query entity counts 1.0; mention of an entity that
    co-occurs with a query entity (1-hop through a Chunk bridge) counts
    `graph_expansion_weight`."""

    DIRECT_QUERY = """
        MATCH (c:Chunk {tenant_id: $tid})-[:MENTIONS]->(e:Entity {tenant_id: $tid})
        WHERE e.norm IN $norms
        RETURN c.chunk_id AS chunk_id, count(DISTINCT e) AS matches
    """

    EXPANSION_QUERY = """
        MATCH (q:Entity {tenant_id: $tid}) WHERE q.norm IN $norms
        MATCH (q)<-[:MENTIONS]-(:Chunk {tenant_id: $tid})-[:MENTIONS]->(nb:Entity)
        WHERE NOT nb.norm IN $norms
        WITH DISTINCT nb
        MATCH (c:Chunk {tenant_id: $tid})-[:MENTIONS]->(nb)
        RETURN c.chunk_id AS chunk_id, count(DISTINCT nb) AS matches
    """

    def __init__(self, driver: AsyncDriver) -> None:
        self.driver = driver

    async def search(
        self, *, tenant_id: uuid.UUID, entity_norms: list[str], limit: int
    ) -> list[uuid.UUID]:
        params = {"tid": str(tenant_id), "norms": entity_norms}
        scores: dict[str, float] = {}
        async with self.driver.session() as session:
            for record in await (await session.run(self.DIRECT_QUERY, params)).data():
                scores[record["chunk_id"]] = record["matches"] * 1.0
            for record in await (await session.run(self.EXPANSION_QUERY, params)).data():
                scores[record["chunk_id"]] = (
                    scores.get(record["chunk_id"], 0.0)
                    + record["matches"] * settings.graph_expansion_weight
                )
        ranked = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
        return [uuid.UUID(chunk_id) for chunk_id in ranked[:limit]]
