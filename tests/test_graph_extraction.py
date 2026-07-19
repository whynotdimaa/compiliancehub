from app.graph.extraction import (
    CompositeExtractor,
    Entity,
    EntityType,
    LLMEntityExtractor,
    RegexEntityExtractor,
    normalize,
)

TEXT = (
    "Under GDPR Article 30, controllers keep processing records. "
    "Our ISMS follows ISO/IEC 27001:2022 and SOC 2; see Section 4.2 and Annex A. "
    "PCI DSS applies to card data. GDPR is mentioned twice."
)


def test_regex_extracts_known_entities():
    entities = {normalize(e.name): e.type for e in RegexEntityExtractor().extract(TEXT)}
    assert entities["gdpr"] == EntityType.REGULATION
    assert entities["iso/iec 27001:2022"] == EntityType.STANDARD
    assert entities["soc 2"] == EntityType.STANDARD
    assert entities["pci dss"] == EntityType.REGULATION
    assert entities["article 30"] == EntityType.REFERENCE
    assert entities["section 4.2"] == EntityType.REFERENCE
    assert entities["annex a"] == EntityType.REFERENCE


def test_regex_dedupes_repeated_mentions():
    entities = RegexEntityExtractor().extract("GDPR, gdpr and GDPR again")
    assert len(entities) == 1


def test_regex_no_entities():
    assert RegexEntityExtractor().extract("nothing relevant here") == []


def test_normalize_collapses_whitespace_and_case():
    assert normalize("  ISO/IEC   27001 ") == "iso/iec 27001"


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, messages, **kwargs) -> str:
        return self.response


def test_llm_extractor_parses_json():
    llm = FakeLLM('[{"name": "data protection officer", "type": "obligation"}]')
    entities = LLMEntityExtractor(llm).extract("text")
    assert entities == [Entity(name="data protection officer", type=EntityType.OBLIGATION)]


def test_llm_extractor_parses_fenced_json():
    llm = FakeLLM('```json\n[{"name": "GDPR", "type": "regulation"}]\n```')
    assert LLMEntityExtractor(llm).extract("text") == [
        Entity(name="GDPR", type=EntityType.REGULATION)
    ]


def test_llm_extractor_invalid_json_returns_empty():
    assert LLMEntityExtractor(FakeLLM("sorry, no entities!")).extract("text") == []


def test_llm_extractor_skips_invalid_items():
    llm = FakeLLM(
        '[{"name": "GDPR", "type": "regulation"}, {"name": "", "type": "regulation"}, '
        '{"name": "X", "type": "not-a-type"}, "just-a-string"]'
    )
    entities = LLMEntityExtractor(llm).extract("text")
    assert [e.name for e in entities] == ["GDPR"]


def test_llm_extractor_survives_llm_failure():
    class ExplodingLLM:
        def complete(self, messages, **kwargs):
            raise RuntimeError("boom")

    assert LLMEntityExtractor(ExplodingLLM()).extract("text") == []


def test_composite_dedupes_across_extractors():
    llm = FakeLLM(
        '[{"name": "gdpr", "type": "regulation"}, {"name": "DPO", "type": "organization"}]'
    )
    composite = CompositeExtractor([RegexEntityExtractor(), LLMEntityExtractor(llm)])
    entities = composite.extract("GDPR applies.")
    names = [e.name for e in entities]
    assert names == ["GDPR", "DPO"]  # regex GDPR wins, LLM duplicate dropped
