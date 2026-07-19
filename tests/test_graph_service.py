"""GraphWriter / GraphSearcher against fake Neo4j drivers.

Cypher itself is validated by the gated live test (tests/integration,
RUN_NEO4J=1); here we verify the parameters we send and the score merge."""
import uuid

from app.graph.extraction import Entity, EntityType
from app.graph.service import ChunkEntities, GraphSearcher, GraphWriter

# --- Writer ------------------------------------------------------------------


class FakeTx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, **params):
        self.calls.append((" ".join(query.split()), params))


class FakeSyncSession:
    def __init__(self, tx: FakeTx) -> None:
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self.tx.run(query, **params)

    def execute_write(self, fn, **kwargs):
        return fn(self.tx, **kwargs)


class FakeSyncDriver:
    def __init__(self) -> None:
        self.tx = FakeTx()

    def session(self):
        return FakeSyncSession(self.tx)


def test_rebuild_document_params_and_order():
    driver = FakeSyncDriver()
    tenant_id, document_id = uuid.uuid4(), uuid.uuid4()
    chunk_id = uuid.uuid4()

    mentions = GraphWriter(driver).rebuild_document(
        tenant_id=tenant_id,
        document_id=document_id,
        title="Policy",
        doc_type="policy",
        chunks=[
            ChunkEntities(
                chunk_id=chunk_id,
                chunk_index=0,
                entities=[
                    Entity(name="GDPR", type=EntityType.REGULATION),
                    Entity(name="Article 30", type=EntityType.REFERENCE),
                ],
            )
        ],
    )

    assert mentions == 2
    queries = [q for q, _ in driver.tx.calls]
    # idempotency: stale chunks deleted before anything is merged
    assert "DETACH DELETE" in queries[0]
    assert "MERGE (d:Document" in queries[1]

    mention_params = driver.tx.calls[3][1]
    rows = mention_params["rows"]
    assert rows[0]["key"] == f"{tenant_id}|gdpr"
    assert rows[1]["norm"] == "article 30"
    assert all(row["chunk_id"] == str(chunk_id) for row in rows)


def test_rebuild_empty_document_still_cleans_graph():
    driver = FakeSyncDriver()
    mentions = GraphWriter(driver).rebuild_document(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        title="Empty",
        doc_type="other",
        chunks=[],
    )
    assert mentions == 0
    assert any("DETACH DELETE" in q for q, _ in driver.tx.calls)


# --- Searcher ----------------------------------------------------------------


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def data(self):
        return self.rows


class FakeAsyncSession:
    def __init__(self, results: list[list[dict]]) -> None:
        self.results = list(results)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def run(self, query, params):
        return FakeResult(self.results.pop(0))


class FakeAsyncDriver:
    def __init__(self, results: list[list[dict]]) -> None:
        self.results = results

    def session(self):
        return FakeAsyncSession(self.results)


async def test_searcher_merges_direct_and_expansion_scores():
    c1, c2, c3 = (uuid.uuid4() for _ in range(3))
    driver = FakeAsyncDriver(
        [
            # direct: c1 matches 2 query entities, c2 matches 1
            [
                {"chunk_id": str(c1), "matches": 2},
                {"chunk_id": str(c2), "matches": 1},
            ],
            # expansion (weight 0.4): c2 +3 neighbors, c3 +1
            [
                {"chunk_id": str(c2), "matches": 3},
                {"chunk_id": str(c3), "matches": 1},
            ],
        ]
    )
    ranked = await GraphSearcher(driver).search(
        tenant_id=uuid.uuid4(), entity_norms=["gdpr"], limit=10
    )
    # c2 = 1 + 3*0.4 = 2.2, c1 = 2.0, c3 = 0.4
    assert ranked == [c2, c1, c3]


async def test_searcher_respects_limit():
    ids = [uuid.uuid4() for _ in range(5)]
    driver = FakeAsyncDriver(
        [[{"chunk_id": str(i), "matches": n} for n, i in enumerate(ids, 1)], []]
    )
    ranked = await GraphSearcher(driver).search(
        tenant_id=uuid.uuid4(), entity_norms=["x"], limit=2
    )
    assert len(ranked) == 2
