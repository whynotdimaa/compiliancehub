"""Live Neo4j smoke: validates the actual Cypher (writer + searcher).

Run with the docker-compose Neo4j (bolt published on 7687):
    RUN_NEO4J=1 NEO4J_URI=bolt://localhost:7687 pytest tests/integration -m integration
"""
import os
import uuid

import pytest

from app.graph.extraction import Entity, EntityType
from app.graph.service import ChunkEntities, GraphSearcher, GraphWriter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_NEO4J") != "1", reason="set RUN_NEO4J=1 to run"),
]


@pytest.fixture
def sync_driver():
    from neo4j import GraphDatabase

    from app.core.config import settings

    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    yield driver
    driver.close()


@pytest.fixture
async def async_driver():
    from neo4j import AsyncGraphDatabase

    from app.core.config import settings

    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    yield driver
    await driver.close()


@pytest.fixture
def seeded_graph(sync_driver):
    """Two chunks: one mentions GDPR+Article 30, one mentions only Article 30."""
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_a, chunk_b = uuid.uuid4(), uuid.uuid4()

    writer = GraphWriter(sync_driver)
    writer.ensure_constraints()
    writer.rebuild_document(
        tenant_id=tenant_id,
        document_id=document_id,
        title="Policy",
        doc_type="policy",
        chunks=[
            ChunkEntities(
                chunk_id=chunk_a,
                chunk_index=0,
                entities=[
                    Entity(name="GDPR", type=EntityType.REGULATION),
                    Entity(name="Article 30", type=EntityType.REFERENCE),
                ],
            ),
            ChunkEntities(
                chunk_id=chunk_b,
                chunk_index=1,
                entities=[Entity(name="Article 30", type=EntityType.REFERENCE)],
            ),
        ],
    )

    yield tenant_id, document_id, chunk_a, chunk_b

    with sync_driver.session() as session:
        session.run(
            "MATCH (n {tenant_id: $tid}) DETACH DELETE n", tid=str(tenant_id)
        )


async def test_direct_match_ranks_by_entity_count(seeded_graph, async_driver):
    tenant_id, _, chunk_a, chunk_b = seeded_graph
    ranked = await GraphSearcher(async_driver).search(
        tenant_id=tenant_id, entity_norms=["gdpr", "article 30"], limit=10
    )
    # chunk_a mentions both query entities, chunk_b only one
    assert ranked[0] == chunk_a
    assert set(ranked) == {chunk_a, chunk_b}


async def test_expansion_reaches_co_occurring_entities(seeded_graph, async_driver):
    tenant_id, _, chunk_a, chunk_b = seeded_graph
    # query only GDPR: chunk_b never mentions it, but Article 30 co-occurs
    # with GDPR in chunk_a -> chunk_b is reachable via expansion
    ranked = await GraphSearcher(async_driver).search(
        tenant_id=tenant_id, entity_norms=["gdpr"], limit=10
    )
    assert chunk_a == ranked[0]
    assert chunk_b in ranked


async def test_other_tenant_sees_nothing(seeded_graph, async_driver):
    ranked = await GraphSearcher(async_driver).search(
        tenant_id=uuid.uuid4(), entity_norms=["gdpr", "article 30"], limit=10
    )
    assert ranked == []


def test_rebuild_is_idempotent(seeded_graph, sync_driver):
    tenant_id, document_id, chunk_a, _ = seeded_graph
    writer = GraphWriter(sync_driver)
    writer.rebuild_document(
        tenant_id=tenant_id,
        document_id=document_id,
        title="Policy",
        doc_type="policy",
        chunks=[
            ChunkEntities(
                chunk_id=chunk_a,
                chunk_index=0,
                entities=[Entity(name="GDPR", type=EntityType.REGULATION)],
            )
        ],
    )
    with sync_driver.session() as session:
        count = session.run(
            "MATCH (c:Chunk {tenant_id: $tid}) RETURN count(c) AS n", tid=str(tenant_id)
        ).single()["n"]
    assert count == 1  # chunk_b from the previous build is gone
