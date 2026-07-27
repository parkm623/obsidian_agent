import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


class NoteUtilityTests(unittest.TestCase):
    def test_note_path_sanitizes_nested_titles_and_rejects_empty_paths(self):
        from obsidian_agent.notes import note_path

        vault_path = Path("vault").resolve()

        self.assertEqual(note_path("Projects/Bad:Name", vault_path), vault_path / "Projects" / "Bad_Name.md")

        with self.assertRaises(ValueError):
            note_path("../", vault_path)

    def test_extract_tags_and_links_from_markdown(self):
        from obsidian_agent.notes import extract_links, extract_tags

        content = (
            "---\n"
            "tags:\n"
            "  - frontmatter\n"
            "---\n\n"
            "Body has #inline/tag and [[Project Alpha|Alpha]] plus [[Daily Note]]."
        )

        self.assertEqual(extract_tags(content), ["frontmatter", "inline/tag"])
        self.assertEqual(extract_links(content), ["Daily Note", "Project Alpha"])


class IndexUtilityTests(unittest.TestCase):
    def test_note_index_row_extracts_metadata(self):
        from obsidian_agent.index import note_index_row

        with tempfile.TemporaryDirectory() as temp_dir:
            vault_path = Path(temp_dir)
            note = vault_path / "Projects" / "Alpha.md"
            note.parent.mkdir()
            note.write_text("---\ntags: [project]\n---\n\nSee [[Beta]] and #active.", encoding="utf-8")

            row = note_index_row(note, vault_path, "2026-06-18T00:00:00")

        self.assertEqual(row["path"], "Projects/Alpha.md")
        self.assertEqual(row["title"], "Projects/Alpha")
        self.assertEqual(row["tags"], '["active", "project"]')
        self.assertEqual(row["links"], '["Beta"]')
        self.assertRegex(row["content_hash"], r"^[0-9a-f]{64}$")

    def test_markdown_note_paths_respects_ignored_folders(self):
        from obsidian_agent.index import markdown_note_paths

        with tempfile.TemporaryDirectory() as temp_dir:
            vault_path = Path(temp_dir)
            (vault_path / "Keep.md").write_text("keep", encoding="utf-8")
            ignored = vault_path / "Archive"
            ignored.mkdir()
            (ignored / "Hidden.md").write_text("hidden", encoding="utf-8")

            paths = markdown_note_paths(vault_path, {"Archive"})

        self.assertEqual([path.name for path in paths], ["Keep.md"])


class KnowledgeUtilityTests(unittest.TestCase):
    def test_knowledge_records_work_with_connection_factory(self):
        from obsidian_agent.index import connect, ensure_schema
        from obsidian_agent.knowledge import (
            add_relation_record,
            get_knowledge_graph_records,
            upsert_entity_record,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "index.sqlite3"
            connect_to_index = lambda: connect(index_path)

            self.assertEqual(
                upsert_entity_record(connect_to_index, ensure_schema, "Concept A", "Topic", ["first"]),
                "OK: upserted entity 'Concept A'.",
            )
            self.assertEqual(
                add_relation_record(connect_to_index, ensure_schema, "Concept A", "references", "Concept B"),
                "OK: added relation 'Concept A' -> 'references' -> 'Concept B'.",
            )
            graph = get_knowledge_graph_records(connect_to_index, ensure_schema)

        self.assertEqual(
            graph,
            {
                "entities": [
                    {"name": "Concept A", "entity_type": "Topic", "observations": ["first"]},
                    {"name": "Concept B", "entity_type": "Concept", "observations": []},
                ],
                "relations": [{"source": "Concept A", "relation": "references", "target": "Concept B"}],
            },
        )


class ExtractionUtilityTests(unittest.TestCase):
    def test_rule_based_extraction_from_content(self):
        from obsidian_agent.extraction import extract_with_provider_from_content

        result = extract_with_provider_from_content(
            "Projects/Alpha Roadmap",
            "Discuss [[Obsidian Vault]] and #project/alpha.",
        )

        self.assertEqual(result["provider"], "rule_based")
        self.assertEqual(
            result["entities"],
            [
                {"name": "Alpha Roadmap", "entity_type": "Concept", "source": "title", "confidence": 0.4},
                {"name": "Obsidian Vault", "entity_type": "Concept", "source": "wiki_link", "confidence": 0.8},
                {"name": "project/alpha", "entity_type": "Project", "source": "tag", "confidence": 0.6},
            ],
        )
        self.assertEqual(
            result["relations"],
            [
                {
                    "source": "Alpha Roadmap",
                    "relation": "references",
                    "target": "Obsidian Vault",
                    "evidence": "wiki_link",
                    "confidence": 0.7,
                }
            ],
        )

    def test_unknown_extraction_provider_returns_error(self):
        from obsidian_agent.extraction import extract_with_provider_from_content

        result = extract_with_provider_from_content("Note", "body", provider="openai")

        self.assertEqual(result["provider"], "openai")
        self.assertEqual(result["entities"], [])
        self.assertEqual(result["relations"], [])
        self.assertIn("unsupported provider", result["error"])


class SafetyUtilityTests(unittest.TestCase):
    def test_replace_heading_section_preserves_following_sections(self):
        from obsidian_agent.safety import replace_heading_section

        content = "# Title\nold intro\n\n## Details\nold details\n\n## Next\nkeep\n"

        replaced = replace_heading_section(content, "Details", "new details")

        self.assertIsNotNone(replaced)
        new_content, old_section = replaced
        self.assertIn("## Details\nold details\n", old_section)
        self.assertIn("## Details\nnew details\n\n## Next\nkeep\n", new_content)

    def test_create_backup_writes_metadata_and_audit(self):
        from obsidian_agent.safety import create_backup, list_audit_entries, list_backups

        with tempfile.TemporaryDirectory() as temp_dir:
            vault_path = Path(temp_dir) / "vault"
            backup_path = vault_path / ".obsidian_agent" / "backups"
            audit_log_path = vault_path / ".obsidian_agent" / "audit.log"
            note = vault_path / "Projects" / "Alpha.md"
            note.parent.mkdir(parents=True)
            note.write_text("body", encoding="utf-8")

            metadata = create_backup(note, vault_path, backup_path, audit_log_path, "checkpoint")
            backups = list_backups(backup_path, "Projects/Alpha")
            audit_entries = list_audit_entries(audit_log_path)

        self.assertEqual(metadata["title"], "Projects/Alpha")
        self.assertEqual(backups[0]["backup_id"], metadata["backup_id"])
        self.assertEqual(audit_entries[0]["action"], "backup_note")
        self.assertEqual(audit_entries[0]["reason"], "checkpoint")


class ServiceUtilityTests(unittest.TestCase):
    def test_build_note_graph_finds_missing_and_orphan_notes(self):
        from obsidian_agent.services import (
            build_note_graph,
            find_missing_links_in_graph,
            find_orphan_notes_in_graph,
        )

        notes = [
            {"title": "A", "path": "A.md", "tags": [], "links": ["B", "Missing"]},
            {"title": "B", "path": "B.md", "tags": [], "links": []},
            {"title": "C", "path": "C.md", "tags": [], "links": []},
        ]

        graph = build_note_graph(notes, include_unresolved=True)

        self.assertEqual(find_missing_links_in_graph(graph), [{"target": "Missing", "sources": ["A"]}])
        self.assertEqual(find_orphan_notes_in_graph(build_note_graph(notes, include_unresolved=False)), ["C"])

    def test_rebuild_index_and_search_work_without_server_module(self):
        from obsidian_agent.index import connect, ensure_schema
        from obsidian_agent.services import rebuild_index, search_indexed_note_rows

        with tempfile.TemporaryDirectory() as temp_dir:
            vault_path = Path(temp_dir) / "vault"
            vault_path.mkdir()
            (vault_path / "Alpha.md").write_text("Roadmap discussion", encoding="utf-8")
            index_path = Path(temp_dir) / "index.sqlite3"
            connect_to_index = lambda: connect(index_path)

            rebuild_result = rebuild_index(connect_to_index, ensure_schema, vault_path, set())
            search_result = search_indexed_note_rows(connect_to_index, ensure_schema, "Roadmap")

        self.assertEqual(rebuild_result, "OK: indexed 1 notes.")
        self.assertEqual(search_result, [{"title": "Alpha", "path": "Alpha.md"}])


class CliUtilityTests(unittest.TestCase):
    def test_cli_main_dispatches_injected_operations(self):
        from obsidian_agent.cli import cli_main

        calls = []
        operations = {
            "rebuild": lambda: "rebuilt",
            "sync": lambda: "synced",
            "search": lambda query, limit=10: [{"query": query, "limit": limit}],
            "graph": lambda include_unresolved=True: {"include_unresolved": include_unresolved},
            "knowledge_graph": lambda: {"entities": [], "relations": []},
            "export_knowledge_graph": lambda: {"entities": [], "relations": []},
            "missing_links": lambda: [],
            "orphans": lambda: [],
            "status": lambda: {"ok": True},
        }

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(operations, ["search", "needle", "--limit", "3"])
        calls.append(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertIn('"query": "needle"', calls[0])
        self.assertIn('"limit": 3', calls[0])


class WorkflowUtilityTests(unittest.TestCase):
    def test_daily_note_title_normalizes_iso_date(self):
        from obsidian_agent.workflows import daily_note_title

        self.assertEqual(daily_note_title("2026-06-19"), "Daily/2026-06-19")

    def test_capture_inbox_rejects_empty_content(self):
        from obsidian_agent.workflows import capture_inbox

        with tempfile.TemporaryDirectory() as temp_dir:
            result = capture_inbox(Path(temp_dir), "   ")

        self.assertEqual(result, "ERROR: inbox content is required.")

    def test_review_queue_adds_and_lists_pending_items(self):
        from obsidian_agent.workflows import add_review_item, list_review_queue

        with tempfile.TemporaryDirectory() as temp_dir:
            vault_path = Path(temp_dir)
            self.assertEqual(add_review_item(vault_path, "Revisit note", source="Daily"), "OK: added review item.")
            self.assertEqual(
                list_review_queue(vault_path),
                [{"content": "Revisit note", "source": "Daily", "line": 11}],
            )

    def test_review_queue_rejects_empty_items(self):
        from obsidian_agent.workflows import add_review_item

        with tempfile.TemporaryDirectory() as temp_dir:
            result = add_review_item(Path(temp_dir), "")

        self.assertEqual(result, "ERROR: review content is required.")

    def test_complete_review_item_marks_item_done(self):
        from obsidian_agent.workflows import add_review_item, complete_review_item, list_review_queue

        with tempfile.TemporaryDirectory() as temp_dir:
            vault_path = Path(temp_dir)
            add_review_item(vault_path, "Revisit note", source="Daily")

            result = complete_review_item(vault_path, 11)

            self.assertEqual(result, "OK: completed review item on line 11.")
            self.assertEqual(list_review_queue(vault_path), [])

    def test_complete_review_item_rejects_non_pending_line(self):
        from obsidian_agent.workflows import complete_review_item

        with tempfile.TemporaryDirectory() as temp_dir:
            result = complete_review_item(Path(temp_dir), 1)

        self.assertEqual(result, "ERROR: review item line was not found.")

    def test_project_workspace_helpers_create_expected_files(self):
        from obsidian_agent.workflows import create_project_workspace, log_project_update, project_base_title

        with tempfile.TemporaryDirectory() as temp_dir:
            vault_path = Path(temp_dir)
            self.assertEqual(project_base_title("demo"), "Projects/demo")
            result = create_project_workspace(vault_path, "demo")
            update_result = log_project_update(vault_path, "demo", "Implemented logging.")

        self.assertEqual(result, "OK: project workspace 'Projects/demo' is ready.")
        self.assertEqual(update_result, "OK: logged project update.")

    def test_project_workspace_rejects_empty_project_name(self):
        from obsidian_agent.workflows import project_base_title

        with self.assertRaises(ValueError):
            project_base_title(" ")

    def test_record_project_decision_rejects_empty_decision(self):
        from obsidian_agent.workflows import record_project_decision

        with tempfile.TemporaryDirectory() as temp_dir:
            result = record_project_decision(Path(temp_dir), "demo", "")

        self.assertEqual(result, "ERROR: project decision is required.")
