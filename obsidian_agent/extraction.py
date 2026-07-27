from pathlib import Path

from obsidian_agent.notes import extract_links, extract_tags


def entity_type_for_candidate(name: str, source: str) -> str:
    lowered = name.lower()
    if source == "tag" and ("project" in lowered or lowered.startswith("proj/")):
        return "Project"
    return "Concept"


def merge_entity_proposal(
    proposals: dict[str, dict[str, object]],
    name: str,
    source: str,
    confidence: float,
) -> None:
    clean_name = name.strip()
    if not clean_name:
        return

    proposal = {
        "name": clean_name,
        "entity_type": entity_type_for_candidate(clean_name, source),
        "source": source,
        "confidence": confidence,
    }
    current = proposals.get(clean_name)
    if current is None or confidence > current["confidence"]:
        proposals[clean_name] = proposal


def propose_entities(note_title: str, content: str) -> list[dict[str, object]]:
    proposals: dict[str, dict[str, object]] = {}
    clean_title = Path(note_title).name
    merge_entity_proposal(proposals, clean_title, "title", 0.4)

    for link in extract_links(content):
        merge_entity_proposal(proposals, link.split("/")[-1] if "/" in link else link, "wiki_link", 0.8)

    for tag in extract_tags(content):
        merge_entity_proposal(proposals, tag, "tag", 0.6)

    source_order = {"title": 0, "wiki_link": 1, "tag": 2}
    return sorted(
        proposals.values(),
        key=lambda proposal: (source_order.get(str(proposal["source"]), 99), proposal["name"]),
    )


def propose_relations(note_title: str, content: str) -> list[dict[str, object]]:
    source = Path(note_title).name
    targets = sorted({link.split("/")[-1] if "/" in link else link for link in extract_links(content)})
    return [
        {
            "source": source,
            "relation": "references",
            "target": target,
            "evidence": "wiki_link",
            "confidence": 0.7,
        }
        for target in targets
        if target and target != source
    ]


def extract_with_provider_from_content(
    note_title: str,
    content: str,
    provider: str = "rule_based",
) -> dict[str, object]:
    clean_provider = provider.strip() if provider and provider.strip() else "rule_based"
    if clean_provider != "rule_based":
        return {
            "provider": clean_provider,
            "entities": [],
            "relations": [],
            "error": f"unsupported provider: {clean_provider}",
        }

    return {
        "provider": "rule_based",
        "entities": propose_entities(note_title, content),
        "relations": propose_relations(note_title, content),
    }
