import sqlite3
from collections.abc import Callable
from datetime import datetime


ConnectionFactory = Callable[[], sqlite3.Connection]
SchemaInitializer = Callable[[sqlite3.Connection], None]


def normalize_observations(observations: object) -> list[str]:
    if observations is None:
        return []
    if isinstance(observations, str):
        return [observations.strip()] if observations.strip() else []
    try:
        iterator = iter(observations)
    except TypeError:
        return [str(observations).strip()]
    return sorted({str(item).strip() for item in iterator if str(item).strip()})


def ensure_entity(
    connection: sqlite3.Connection,
    name: str,
    entity_type: str = "Concept",
    updated_at: str | None = None,
    update_type: bool = True,
) -> None:
    timestamp = updated_at or datetime.now().isoformat(timespec="seconds")
    if update_type:
        conflict_clause = """
            entity_type = excluded.entity_type,
            updated_at = excluded.updated_at
        """
    else:
        conflict_clause = """
            updated_at = excluded.updated_at
        """
    connection.execute(
        f"""
        INSERT INTO entities (name, entity_type, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET {conflict_clause}
        """,
        (name, entity_type, timestamp),
    )


def upsert_entity_record(
    connect: ConnectionFactory,
    ensure_schema: SchemaInitializer,
    name: str,
    entity_type: str = "Concept",
    observations: object = None,
) -> str:
    clean_name = name.strip()
    clean_type = entity_type.strip() if entity_type and entity_type.strip() else "Concept"
    if not clean_name:
        return "ERROR: entity name is required."

    timestamp = datetime.now().isoformat(timespec="seconds")
    try:
        connection = connect()
        try:
            ensure_schema(connection)
            ensure_entity(connection, clean_name, clean_type, timestamp)
            connection.executemany(
                """
                INSERT OR IGNORE INTO entity_observations (entity_name, observation, created_at)
                VALUES (?, ?, ?)
                """,
                [(clean_name, observation, timestamp) for observation in normalize_observations(observations)],
            )
            connection.commit()
        finally:
            connection.close()
        return f"OK: upserted entity '{clean_name}'."
    except sqlite3.Error as exc:
        return f"ERROR: failed to upsert entity: {exc}"


def add_relation_record(connect: ConnectionFactory, ensure_schema: SchemaInitializer, source: str, relation: str, target: str) -> str:
    clean_source = source.strip()
    clean_relation = relation.strip()
    clean_target = target.strip()
    if not clean_source or not clean_relation or not clean_target:
        return "ERROR: source, relation, and target are required."

    timestamp = datetime.now().isoformat(timespec="seconds")
    try:
        connection = connect()
        try:
            ensure_schema(connection)
            ensure_entity(connection, clean_source, updated_at=timestamp, update_type=False)
            ensure_entity(connection, clean_target, updated_at=timestamp, update_type=False)
            connection.execute(
                """
                INSERT OR IGNORE INTO relations (source, relation, target, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (clean_source, clean_relation, clean_target, timestamp),
            )
            connection.commit()
        finally:
            connection.close()
        return f"OK: added relation '{clean_source}' -> '{clean_relation}' -> '{clean_target}'."
    except sqlite3.Error as exc:
        return f"ERROR: failed to add relation: {exc}"


def get_knowledge_graph_records(
    connect: ConnectionFactory,
    ensure_schema: SchemaInitializer,
) -> dict[str, list[dict[str, object]]]:
    try:
        connection = connect()
        try:
            ensure_schema(connection)
            entity_rows = connection.execute(
                """
                SELECT name, entity_type
                FROM entities
                ORDER BY name
                """
            ).fetchall()
            observation_rows = connection.execute(
                """
                SELECT entity_name, observation
                FROM entity_observations
                ORDER BY entity_name, observation
                """
            ).fetchall()
            relation_rows = connection.execute(
                """
                SELECT source, relation, target
                FROM relations
                ORDER BY source, relation, target
                """
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return {"entities": [], "relations": []}

    observations_by_entity: dict[str, list[str]] = {}
    for row in observation_rows:
        observations_by_entity.setdefault(row["entity_name"], []).append(row["observation"])

    return {
        "entities": [
            {
                "name": row["name"],
                "entity_type": row["entity_type"],
                "observations": observations_by_entity.get(row["name"], []),
            }
            for row in entity_rows
        ],
        "relations": [dict(row) for row in relation_rows],
    }


def import_knowledge_graph_records(
    connect: ConnectionFactory,
    ensure_schema: SchemaInitializer,
    data: dict[str, object],
    merge: bool = True,
) -> str:
    entities = data.get("entities", []) if isinstance(data, dict) else []
    relations = data.get("relations", []) if isinstance(data, dict) else []
    imported_entities = 0
    imported_relations = 0

    try:
        connection = connect()
        try:
            ensure_schema(connection)
            if not merge:
                connection.execute("DELETE FROM relations")
                connection.execute("DELETE FROM entity_observations")
                connection.execute("DELETE FROM entities")

            timestamp = datetime.now().isoformat(timespec="seconds")
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                name = str(entity.get("name", "")).strip()
                if not name:
                    continue
                entity_type = str(entity.get("entity_type", "Concept")).strip() or "Concept"
                ensure_entity(connection, name, entity_type, timestamp)
                observations = normalize_observations(entity.get("observations", []))
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO entity_observations (entity_name, observation, created_at)
                    VALUES (?, ?, ?)
                    """,
                    [(name, observation, timestamp) for observation in observations],
                )
                imported_entities += 1

            for relation_row in relations:
                if not isinstance(relation_row, dict):
                    continue
                source = str(relation_row.get("source", "")).strip()
                relation = str(relation_row.get("relation", "")).strip()
                target = str(relation_row.get("target", "")).strip()
                if not source or not relation or not target:
                    continue
                ensure_entity(connection, source, updated_at=timestamp, update_type=False)
                ensure_entity(connection, target, updated_at=timestamp, update_type=False)
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO relations (source, relation, target, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (source, relation, target, timestamp),
                )
                imported_relations += cursor.rowcount

            connection.commit()
        finally:
            connection.close()

        return f"OK: imported knowledge graph (entities={imported_entities}, relations={imported_relations})."
    except sqlite3.Error as exc:
        return f"ERROR: failed to import knowledge graph: {exc}"


def link_note_to_entity_record(
    connect: ConnectionFactory,
    ensure_schema: SchemaInitializer,
    note_title: str,
    note_path: str,
    entity_name: str,
    relation: str = "references",
) -> str:
    clean_entity = entity_name.strip()
    clean_relation = relation.strip() if relation and relation.strip() else "references"
    if not clean_entity:
        return "ERROR: entity name is required."

    timestamp = datetime.now().isoformat(timespec="seconds")
    try:
        connection = connect()
        try:
            ensure_schema(connection)
            ensure_entity(connection, clean_entity, updated_at=timestamp, update_type=False)
            connection.execute(
                """
                INSERT OR IGNORE INTO note_entities
                    (note_path, note_title, entity_name, relation, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (note_path, note_title, clean_entity, clean_relation, timestamp),
            )
            connection.commit()
        finally:
            connection.close()

        return f"OK: linked note '{note_title}' to entity '{clean_entity}'."
    except sqlite3.Error as exc:
        return f"ERROR: failed to link note to entity: {exc}"


def get_entity_note_records(
    connect: ConnectionFactory,
    ensure_schema: SchemaInitializer,
    entity_name: str,
) -> list[dict[str, str]]:
    clean_entity = entity_name.strip()
    if not clean_entity:
        return []

    try:
        connection = connect()
        try:
            ensure_schema(connection)
            rows = connection.execute(
                """
                SELECT entity_name, note_title, note_path, relation
                FROM note_entities
                WHERE entity_name = ?
                ORDER BY note_title, relation
                """,
                (clean_entity,),
            ).fetchall()
        finally:
            connection.close()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
