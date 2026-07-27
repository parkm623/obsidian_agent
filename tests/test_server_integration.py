import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests.helpers import load_server


class ObsidianServerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_path = Path(self.temp_dir.name)
        self.server = load_server(self.vault_path)

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        os.environ.pop("OBSIDIAN_AGENT_CONFIG", None)
        sys.modules.pop("server", None)

    def test_create_note_writes_frontmatter_and_content(self):
        result = self.server.create_note("Projects/Test Note", "# Hello", ["test", "mcp"])

        self.assertEqual(result, "OK: created 'Projects/Test Note'.")
        note = self.vault_path / "Projects" / "Test Note.md"
        self.assertTrue(note.exists())
        content = note.read_text(encoding="utf-8")
        self.assertIn("tags:\n  - test\n  - mcp", content)
        self.assertIn("# Hello", content)

    def test_append_note_creates_missing_note(self):
        result = self.server.append_to_note("Inbox/New", "first line")

        self.assertEqual(result, "OK: appended to 'Inbox/New'.")
        self.assertEqual((self.vault_path / "Inbox" / "New.md").read_text(encoding="utf-8"), "first line\n")

    def test_create_daily_note_creates_dated_template(self):
        result = self.server.create_daily_note("2026-06-19")

        self.assertEqual(result, "OK: created daily note 'Daily/2026-06-19'.")
        content = (self.vault_path / "Daily" / "2026-06-19.md").read_text(encoding="utf-8")
        self.assertIn("tags:\n  - daily", content)
        self.assertIn("# 2026-06-19", content)
        self.assertIn("## Inbox", content)
        self.assertIn("## Review", content)

    def test_capture_inbox_appends_timestamped_item(self):
        result = self.server.capture_inbox("Read about graph databases", source="browser")

        self.assertEqual(result, "OK: captured inbox item.")
        content = (self.vault_path / "Inbox.md").read_text(encoding="utf-8")
        self.assertIn("- [", content)
        self.assertIn("Read about graph databases", content)
        self.assertIn("(source: browser)", content)

    def test_add_and_list_review_queue_items(self):
        add_result = self.server.add_review_item("Summarize [[Paper A]]", source="Inbox")

        self.assertEqual(add_result, "OK: added review item.")
        content = (self.vault_path / "Review Queue.md").read_text(encoding="utf-8")
        self.assertIn("- [ ]", content)
        self.assertIn("Summarize [[Paper A]]", content)
        self.assertIn("(source: Inbox)", content)
        self.assertEqual(
            self.server.list_review_queue(),
            [{"content": "Summarize [[Paper A]]", "source": "Inbox", "line": 11}],
        )

    def test_complete_review_item_marks_line_done(self):
        self.server.add_review_item("Summarize [[Paper A]]", source="Inbox")

        result = self.server.complete_review_item(11)

        self.assertEqual(result, "OK: completed review item on line 11.")
        content = (self.vault_path / "Review Queue.md").read_text(encoding="utf-8")
        self.assertIn("- [x] Summarize [[Paper A]] (source: Inbox)", content)
        self.assertEqual(self.server.list_review_queue(), [])

    def test_project_workspace_logs_updates_decisions_and_ideas(self):
        workspace_result = self.server.create_project_workspace("obsidian-agent")
        update_result = self.server.log_project_update("obsidian-agent", "Added project memory tools.")
        decision_result = self.server.record_project_decision(
            "obsidian-agent",
            "Keep project memory tools append-only.",
            "Avoid workflow complexity before real use.",
        )
        idea_result = self.server.capture_project_idea("obsidian-agent", "Use this MCP in new repos.")

        self.assertEqual(workspace_result, "OK: project workspace 'Projects/obsidian-agent' is ready.")
        self.assertEqual(update_result, "OK: logged project update.")
        self.assertEqual(decision_result, "OK: recorded project decision.")
        self.assertEqual(idea_result, "OK: captured project idea.")
        self.assertTrue((self.vault_path / "Projects" / "obsidian-agent" / "Overview.md").exists())
        self.assertIn(
            "Added project memory tools.",
            (self.vault_path / "Projects" / "obsidian-agent" / "Dev Log.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "Keep project memory tools append-only.",
            (self.vault_path / "Projects" / "obsidian-agent" / "Decisions.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "Use this MCP in new repos.",
            (self.vault_path / "Projects" / "obsidian-agent" / "Ideas.md").read_text(encoding="utf-8"),
        )

    def test_duplicate_create_gets_timestamped_copy(self):
        first = self.server.create_note("Duplicate", "one", None)
        second = self.server.create_note("Duplicate", "two", None)

        self.assertEqual(first, "OK: created 'Duplicate'.")
        self.assertTrue(second.startswith("OK: created 'Duplicate_"))
        self.assertEqual(len(list(self.vault_path.glob("Duplicate*.md"))), 2)

    def test_search_finds_note_name_and_content(self):
        self.server.create_note("Meetings/Weekly", "Roadmap discussion", "meeting")

        self.assertEqual(self.server.search_notes("weekly"), ["Meetings/Weekly"])
        self.assertEqual(self.server.search_notes("roadmap"), ["Meetings/Weekly"])
        self.assertEqual(self.server.search_notes(""), [])

    def test_unsafe_or_empty_paths_are_rejected(self):
        self.assertTrue(self.server.create_note("../", "bad", None).startswith("ERROR:"))
        self.assertFalse((self.vault_path.parent / ".md").exists())

    def test_config_file_can_set_vault_path_and_ignored_folders(self):
        config_temp_dir = tempfile.TemporaryDirectory()
        try:
            configured_vault = Path(config_temp_dir.name) / "configured_vault"
            config_file = Path(config_temp_dir.name) / "obsidian_agent.toml"
            config_file.write_text(
                f'vault_path = "{configured_vault.as_posix()}"\n'
                'ignored_folders = ["Archive"]\n',
                encoding="utf-8",
            )
            os.environ.pop("OBSIDIAN_VAULT_PATH", None)
            configured_server = load_server(None, config_file)

            configured_server.create_note("Keep", "visible", None)
            configured_server.create_note("Archive/Hidden", "hidden", None)
            configured_server.rebuild_note_index()

            self.assertEqual(configured_server.VAULT_PATH, configured_vault.resolve())
            self.assertEqual([row["title"] for row in configured_server.get_indexed_notes()], ["Keep"])
        finally:
            config_temp_dir.cleanup()
            sys.modules.pop("server", None)
            self.server = load_server(self.vault_path)

    def test_environment_vault_path_overrides_config_vault_path(self):
        config_temp_dir = tempfile.TemporaryDirectory()
        try:
            configured_vault = Path(config_temp_dir.name) / "configured_vault"
            config_file = Path(config_temp_dir.name) / "obsidian_agent.toml"
            config_file.write_text(f'vault_path = "{configured_vault.as_posix()}"\n', encoding="utf-8")

            configured_server = load_server(self.vault_path, config_file)

            self.assertEqual(configured_server.VAULT_PATH, self.vault_path.resolve())
        finally:
            config_temp_dir.cleanup()
            sys.modules.pop("server", None)
            self.server = load_server(self.vault_path)

    def test_rebuild_note_index_records_note_metadata(self):
        self.server.create_note("Projects/Index Me", "indexed content", ["index"])

        result = self.server.rebuild_note_index()
        rows = self.server.get_indexed_notes()

        self.assertEqual(result, "OK: indexed 1 notes.")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], "Projects/Index Me.md")
        self.assertEqual(rows[0]["title"], "Projects/Index Me")
        self.assertGreater(rows[0]["size_bytes"], 0)
        self.assertRegex(rows[0]["content_hash"], r"^[0-9a-f]{64}$")

    def test_rebuild_note_index_removes_deleted_notes(self):
        self.server.create_note("Keep", "still here", None)
        self.server.create_note("Remove", "gone soon", None)
        self.server.rebuild_note_index()
        (self.vault_path / "Remove.md").unlink()

        result = self.server.rebuild_note_index()
        rows = self.server.get_indexed_notes()

        self.assertEqual(result, "OK: indexed 1 notes.")
        self.assertEqual([row["title"] for row in rows], ["Keep"])

    def test_rebuild_note_index_records_tags_and_wiki_links(self):
        content = (
            "Related to [[Projects/Alpha|Alpha Project]] and [[Daily Note]].\n"
            "Inline tags include #meeting and #project/alpha.\n"
        )
        self.server.create_note("Knowledge/Graph Seed", content, ["frontmatter", "project/alpha"])

        self.server.rebuild_note_index()
        rows = self.server.get_indexed_notes()

        self.assertEqual(rows[0]["tags"], ["frontmatter", "meeting", "project/alpha"])
        self.assertEqual(rows[0]["links"], ["Daily Note", "Projects/Alpha"])

    def test_rebuild_note_index_records_inline_frontmatter_tags(self):
        note = self.vault_path / "Manual.md"
        note.write_text(
            "---\n"
            "tags: [manual, inbox]\n"
            "---\n\n"
            "Manual note with #manual/ref and [[Reference]].\n",
            encoding="utf-8",
        )

        self.server.rebuild_note_index()
        rows = self.server.get_indexed_notes()

        self.assertEqual(rows[0]["tags"], ["inbox", "manual", "manual/ref"])
        self.assertEqual(rows[0]["links"], ["Reference"])

    def test_get_note_graph_returns_nodes_and_edges(self):
        self.server.create_note("Projects/Alpha", "Alpha body #project", ["active"])
        self.server.create_note("Daily", "Links to [[Projects/Alpha|Alpha]] and [[Missing Note]].", ["journal"])
        self.server.rebuild_note_index()

        graph = self.server.get_note_graph()

        self.assertEqual(
            graph["nodes"],
            [
                {"id": "Daily", "path": "Daily.md", "tags": ["journal"]},
                {"id": "Projects/Alpha", "path": "Projects/Alpha.md", "tags": ["active", "project"]},
            ],
        )
        self.assertEqual(
            graph["edges"],
            [
                {"source": "Daily", "target": "Missing Note", "resolved": False},
                {"source": "Daily", "target": "Projects/Alpha", "resolved": True},
            ],
        )

    def test_get_note_graph_can_filter_to_resolved_edges(self):
        self.server.create_note("A", "[[B]] [[Ghost]]", None)
        self.server.create_note("B", "target", None)
        self.server.rebuild_note_index()

        graph = self.server.get_note_graph(include_unresolved=False)

        self.assertEqual(graph["edges"], [{"source": "A", "target": "B", "resolved": True}])

    def test_knowledge_graph_can_store_entities_and_relations(self):
        entity_result = self.server.upsert_entity(
            name="Project Alpha",
            entity_type="Project",
            observations=["Uses Obsidian notes", "Needs graph support"],
        )
        relation_result = self.server.add_relation(
            source="Project Alpha",
            relation="depends_on",
            target="Obsidian Vault",
        )

        graph = self.server.get_knowledge_graph()

        self.assertEqual(entity_result, "OK: upserted entity 'Project Alpha'.")
        self.assertEqual(relation_result, "OK: added relation 'Project Alpha' -> 'depends_on' -> 'Obsidian Vault'.")
        self.assertEqual(
            graph["entities"],
            [
                {
                    "name": "Obsidian Vault",
                    "entity_type": "Concept",
                    "observations": [],
                },
                {
                    "name": "Project Alpha",
                    "entity_type": "Project",
                    "observations": ["Needs graph support", "Uses Obsidian notes"],
                },
            ],
        )
        self.assertEqual(
            graph["relations"],
            [
                {
                    "source": "Project Alpha",
                    "relation": "depends_on",
                    "target": "Obsidian Vault",
                }
            ],
        )

    def test_knowledge_graph_deduplicates_entities_observations_and_relations(self):
        self.server.upsert_entity("Concept A", "Concept", ["first"])
        self.server.upsert_entity("Concept A", "Topic", ["first", "second"])
        self.server.add_relation("Concept A", "references", "Concept B")
        self.server.add_relation("Concept A", "references", "Concept B")

        graph = self.server.get_knowledge_graph()

        self.assertEqual(
            graph["entities"],
            [
                {"name": "Concept A", "entity_type": "Topic", "observations": ["first", "second"]},
                {"name": "Concept B", "entity_type": "Concept", "observations": []},
            ],
        )
        self.assertEqual(len(graph["relations"]), 1)

    def test_find_missing_links_groups_unresolved_targets(self):
        self.server.create_note("Daily", "[[Missing]] [[Ideas/Later]]", None)
        self.server.create_note("Project", "Also references [[Missing]].", None)
        self.server.create_note("Existing", "target", None)
        self.server.create_note("Linked", "[[Existing]]", None)
        self.server.rebuild_note_index()

        self.assertEqual(
            self.server.find_missing_links(),
            [
                {"target": "Ideas/Later", "sources": ["Daily"]},
                {"target": "Missing", "sources": ["Daily", "Project"]},
            ],
        )

    def test_find_orphan_notes_returns_notes_without_incoming_or_outgoing_links(self):
        self.server.create_note("A", "[[B]]", None)
        self.server.create_note("B", "target", None)
        self.server.create_note("C", "standalone", None)
        self.server.rebuild_note_index()

        self.assertEqual(self.server.find_orphan_notes(), ["C"])

    def test_search_indexed_notes_finds_title_and_content(self):
        self.server.create_note("Research/Vector Search", "Embeddings and ranking notes.", ["search"])
        self.server.create_note("Daily", "Today I tuned ranking behavior.", None)
        self.server.rebuild_note_index()

        self.assertEqual(
            self.server.search_indexed_notes("ranking"),
            [
                {"title": "Daily", "path": "Daily.md"},
                {"title": "Research/Vector Search", "path": "Research/Vector Search.md"},
            ],
        )
        self.assertEqual(
            self.server.search_indexed_notes("Vector"),
            [{"title": "Research/Vector Search", "path": "Research/Vector Search.md"}],
        )

    def test_search_indexed_notes_respects_limit_and_empty_query(self):
        self.server.create_note("A", "common term", None)
        self.server.create_note("B", "common term", None)
        self.server.rebuild_note_index()

        self.assertEqual(len(self.server.search_indexed_notes("common", limit=1)), 1)
        self.assertEqual(self.server.search_indexed_notes("   "), [])

    def test_sync_note_index_adds_updates_and_removes_notes(self):
        self.server.create_note("Keep", "old content", None)
        self.server.create_note("Remove", "delete me", None)
        self.server.rebuild_note_index()

        (self.vault_path / "Keep.md").write_text("new searchable content", encoding="utf-8")
        (self.vault_path / "Remove.md").unlink()
        self.server.create_note("Add", "fresh searchable content", None)

        result = self.server.sync_note_index()
        rows = self.server.get_indexed_notes()

        self.assertEqual(result, "OK: synced index (added=1, updated=1, removed=1, unchanged=0).")
        self.assertEqual([row["title"] for row in rows], ["Add", "Keep"])
        self.assertEqual(
            self.server.search_indexed_notes("fresh"),
            [{"title": "Add", "path": "Add.md"}],
        )
        self.assertEqual(
            self.server.search_indexed_notes("new"),
            [{"title": "Keep", "path": "Keep.md"}],
        )

    def test_sync_note_index_reports_unchanged_notes(self):
        self.server.create_note("Stable", "same content", None)
        self.server.rebuild_note_index()

        self.assertEqual(
            self.server.sync_note_index(),
            "OK: synced index (added=0, updated=0, removed=0, unchanged=1).",
        )

    def test_preview_note_update_returns_diff_without_writing(self):
        self.server.create_note("Draft", "old line\nsame line", None)

        preview = self.server.preview_note_update("Draft", "new line\nsame line")

        self.assertEqual(preview["title"], "Draft")
        self.assertTrue(preview["exists"])
        self.assertIn("-old line", preview["diff"])
        self.assertIn("+new line", preview["diff"])
        self.assertIn("old line", self.server.read_note("Draft"))

    def test_replace_note_writes_audit_log_and_syncs_index(self):
        self.server.create_note("Draft", "old content", None)
        self.server.rebuild_note_index()

        result = self.server.replace_note("Draft", "new indexed content", reason="refresh draft")

        self.assertEqual(result, "OK: replaced 'Draft'.")
        self.assertIn("new indexed content", self.server.read_note("Draft"))
        self.assertEqual(
            self.server.search_indexed_notes("indexed"),
            [{"title": "Draft", "path": "Draft.md"}],
        )
        log = (self.vault_path / ".obsidian_agent" / "audit.log").read_text(encoding="utf-8")
        self.assertIn("replace_note", log)
        self.assertIn("Draft.md", log)
        self.assertIn("refresh draft", log)

    def test_propose_entities_from_note_returns_candidates_without_storing(self):
        self.server.create_note(
            "Projects/Alpha Roadmap",
            "Discuss [[Obsidian Vault]] and #knowledge/graph for the next milestone.",
            ["project/alpha"],
        )

        proposals = self.server.propose_entities_from_note("Projects/Alpha Roadmap")
        graph = self.server.get_knowledge_graph()

        self.assertEqual(
            proposals,
            [
                {
                    "name": "Alpha Roadmap",
                    "entity_type": "Concept",
                    "source": "title",
                    "confidence": 0.4,
                },
                {
                    "name": "Obsidian Vault",
                    "entity_type": "Concept",
                    "source": "wiki_link",
                    "confidence": 0.8,
                },
                {
                    "name": "knowledge/graph",
                    "entity_type": "Concept",
                    "source": "tag",
                    "confidence": 0.6,
                },
                {
                    "name": "project/alpha",
                    "entity_type": "Project",
                    "source": "tag",
                    "confidence": 0.6,
                },
            ],
        )
        self.assertEqual(graph, {"entities": [], "relations": []})

    def test_propose_entities_from_note_handles_missing_note(self):
        self.assertEqual(self.server.propose_entities_from_note("Missing"), [])

    def test_link_note_to_entity_connects_note_and_entity(self):
        self.server.create_note("Projects/Alpha Roadmap", "roadmap body", None)

        link_result = self.server.link_note_to_entity(
            title="Projects/Alpha Roadmap",
            entity_name="Project Alpha",
            relation="documents",
        )

        self.assertEqual(link_result, "OK: linked note 'Projects/Alpha Roadmap' to entity 'Project Alpha'.")
        self.assertEqual(
            self.server.get_entity_notes("Project Alpha"),
            [
                {
                    "entity_name": "Project Alpha",
                    "note_title": "Projects/Alpha Roadmap",
                    "note_path": "Projects/Alpha Roadmap.md",
                    "relation": "documents",
                }
            ],
        )
        self.assertEqual(
            self.server.get_knowledge_graph()["entities"],
            [{"name": "Project Alpha", "entity_type": "Concept", "observations": []}],
        )

    def test_link_note_to_entity_rejects_missing_note_and_deduplicates(self):
        self.assertTrue(self.server.link_note_to_entity("Missing", "Concept A").startswith("ERROR:"))
        self.server.create_note("Note A", "body", None)

        self.server.link_note_to_entity("Note A", "Concept A")
        self.server.link_note_to_entity("Note A", "Concept A")

        self.assertEqual(len(self.server.get_entity_notes("Concept A")), 1)

    def test_preview_replace_section_returns_diff_without_writing(self):
        self.server.create_note("Guide", "# Guide\n\n## Setup\nold setup\n\n## Usage\nkeep usage", None)

        preview = self.server.preview_replace_section("Guide", "Setup", "new setup")

        self.assertTrue(preview["exists"])
        self.assertIn("-old setup", preview["diff"])
        self.assertIn("+new setup", preview["diff"])
        self.assertIn("old setup", self.server.read_note("Guide"))

    def test_replace_section_updates_only_matching_section_and_audits(self):
        self.server.create_note("Guide", "# Guide\n\n## Setup\nold setup\n\n## Usage\nkeep usage", None)
        self.server.rebuild_note_index()

        result = self.server.replace_section("Guide", "Setup", "new indexed setup", reason="refresh setup")

        content = self.server.read_note("Guide")
        self.assertEqual(result, "OK: replaced section 'Setup' in 'Guide'.")
        self.assertIn("## Setup\nnew indexed setup\n\n## Usage\nkeep usage", content)
        self.assertEqual(
            self.server.search_indexed_notes("indexed"),
            [{"title": "Guide", "path": "Guide.md"}],
        )
        log = (self.vault_path / ".obsidian_agent" / "audit.log").read_text(encoding="utf-8")
        self.assertIn("replace_section", log)
        self.assertIn("refresh setup", log)

    def test_replace_section_rejects_missing_section(self):
        self.server.create_note("Guide", "# Guide\n\n## Existing\nbody", None)

        self.assertTrue(self.server.replace_section("Guide", "Missing", "new").startswith("ERROR:"))

    def test_backup_note_creates_restorable_snapshot(self):
        self.server.create_note("Draft", "original body", None)

        backup = self.server.backup_note("Draft", reason="before edit")

        self.assertEqual(backup["title"], "Draft")
        self.assertEqual(backup["path"], "Draft.md")
        self.assertIn("backup_id", backup)
        backup_path = self.vault_path / ".obsidian_agent" / "backups" / backup["backup_id"]
        self.assertTrue(backup_path.exists())
        self.assertEqual(backup_path.read_text(encoding="utf-8"), self.server.read_note("Draft"))

    def test_restore_note_version_restores_content_and_syncs_index(self):
        self.server.create_note("Draft", "original searchable body", None)
        self.server.rebuild_note_index()
        backup = self.server.backup_note("Draft", reason="before replace")
        self.server.replace_note("Draft", "changed body", reason="change")

        result = self.server.restore_note_version(backup["backup_id"], reason="rollback")

        self.assertEqual(result, "OK: restored 'Draft' from backup.")
        self.assertIn("original searchable body", self.server.read_note("Draft"))
        self.assertEqual(
            self.server.search_indexed_notes("original"),
            [{"title": "Draft", "path": "Draft.md"}],
        )
        log = (self.vault_path / ".obsidian_agent" / "audit.log").read_text(encoding="utf-8")
        self.assertIn("restore_note_version", log)
        self.assertIn("rollback", log)

    def test_restore_note_version_rejects_unknown_backup(self):
        self.assertTrue(self.server.restore_note_version("missing.md").startswith("ERROR:"))

    def test_list_audit_log_returns_recent_entries(self):
        self.server.create_note("Draft", "body", None)
        self.server.backup_note("Draft", reason="first")
        self.server.replace_note("Draft", "new body", reason="second")

        entries = self.server.list_audit_log(limit=1)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "replace_note")
        self.assertEqual(entries[0]["path"], "Draft.md")
        self.assertEqual(entries[0]["reason"], "second")

    def test_list_note_backups_filters_by_title_and_gets_metadata(self):
        self.server.create_note("Draft", "draft body", None)
        self.server.create_note("Other", "other body", None)
        draft_backup = self.server.backup_note("Draft", reason="draft backup")
        self.server.backup_note("Other", reason="other backup")

        backups = self.server.list_note_backups("Draft")
        metadata = self.server.get_backup_metadata(draft_backup["backup_id"])

        self.assertEqual([backup["title"] for backup in backups], ["Draft"])
        self.assertEqual(metadata["backup_id"], draft_backup["backup_id"])
        self.assertEqual(metadata["path"], "Draft.md")
        self.assertEqual(metadata["reason"], "draft backup")

    def test_backup_lookup_handles_missing_files(self):
        self.assertEqual(self.server.list_audit_log(), [])
        self.assertEqual(self.server.list_note_backups("Missing"), [])
        self.assertEqual(self.server.get_backup_metadata("missing"), {})

    def test_get_system_status_summarizes_vault_health(self):
        self.server.create_note("A", "[[Missing]]", None)
        self.server.create_note("B", "standalone", None)
        self.server.rebuild_note_index()
        self.server.upsert_entity("Concept A", "Concept", ["obs"])
        self.server.add_relation("Concept A", "references", "Concept B")
        self.server.backup_note("A", reason="status test")

        status = self.server.get_system_status()

        self.assertEqual(status["vault_path"], str(self.vault_path))
        self.assertEqual(status["note_count"], 2)
        self.assertEqual(status["missing_link_count"], 1)
        self.assertEqual(status["orphan_note_count"], 2)
        self.assertEqual(status["entity_count"], 2)
        self.assertEqual(status["relation_count"], 1)
        self.assertEqual(status["backup_count"], 1)
        self.assertEqual(status["recent_audit"][0]["action"], "backup_note")

    def test_export_and_import_knowledge_graph_round_trip(self):
        self.server.upsert_entity("Concept A", "Topic", ["first", "second"])
        self.server.add_relation("Concept A", "references", "Concept B")

        exported = self.server.export_knowledge_graph()

        self.assertEqual(
            exported,
            {
                "entities": [
                    {"name": "Concept A", "entity_type": "Topic", "observations": ["first", "second"]},
                    {"name": "Concept B", "entity_type": "Concept", "observations": []},
                ],
                "relations": [
                    {"source": "Concept A", "relation": "references", "target": "Concept B"},
                ],
            },
        )

        fresh_dir = tempfile.TemporaryDirectory()
        try:
            fresh_server = load_server(Path(fresh_dir.name))
            result = fresh_server.import_knowledge_graph(exported)

            self.assertEqual(result, "OK: imported knowledge graph (entities=2, relations=1).")
            self.assertEqual(fresh_server.get_knowledge_graph(), exported)
        finally:
            fresh_dir.cleanup()

    def test_import_knowledge_graph_replace_mode_clears_existing_graph(self):
        self.server.upsert_entity("Old", "Concept", ["stale"])
        data = {
            "entities": [{"name": "New", "entity_type": "Project", "observations": ["fresh"]}],
            "relations": [],
        }

        result = self.server.import_knowledge_graph(data, merge=False)

        self.assertEqual(result, "OK: imported knowledge graph (entities=1, relations=0).")
        self.assertEqual(
            self.server.get_knowledge_graph(),
            {"entities": [{"name": "New", "entity_type": "Project", "observations": ["fresh"]}], "relations": []},
        )

    def test_cli_main_runs_rebuild_sync_and_search(self):
        self.server.create_note("CLI", "command line search target", None)

        rebuild_output = io.StringIO()
        with redirect_stdout(rebuild_output):
            exit_code = self.server.cli_main(["rebuild"])

        self.assertEqual(exit_code, 0)
        self.assertIn("OK: indexed 1 notes.", rebuild_output.getvalue())

        search_output = io.StringIO()
        with redirect_stdout(search_output):
            exit_code = self.server.cli_main(["search", "target"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"title": "CLI"', search_output.getvalue())

        sync_output = io.StringIO()
        with redirect_stdout(sync_output):
            exit_code = self.server.cli_main(["sync"])

        self.assertEqual(exit_code, 0)
        self.assertIn("OK: synced index", sync_output.getvalue())

    def test_cli_main_outputs_graph_json(self):
        self.server.create_note("A", "[[B]]", None)
        self.server.create_note("B", "target", None)
        self.server.rebuild_note_index()

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = self.server.cli_main(["graph", "--resolved-only"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"source": "A"', output.getvalue())
        self.assertIn('"target": "B"', output.getvalue())

    def test_cli_main_outputs_status_json(self):
        self.server.create_note("Status", "body", None)
        self.server.rebuild_note_index()

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = self.server.cli_main(["status"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"note_count": 1', output.getvalue())

    def test_cli_entry_uses_process_argv(self):
        self.server.create_note("Entry", "entry search target", None)
        self.server.rebuild_note_index()
        old_argv = sys.argv[:]
        sys.argv = ["obsidian-agent", "search", "target"]
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                exit_code = self.server.cli_entry()
        finally:
            sys.argv = old_argv

        self.assertEqual(exit_code, 0)
        self.assertIn('"title": "Entry"', output.getvalue())

    def test_cli_main_exports_knowledge_graph_json(self):
        self.server.upsert_entity("Concept A", "Concept", ["obs"])

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = self.server.cli_main(["export-kg"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"name": "Concept A"', output.getvalue())

    def test_accept_entity_proposals_stores_candidates_above_threshold(self):
        self.server.create_note(
            "Projects/Alpha Roadmap",
            "Discuss [[Obsidian Vault]] and #knowledge/graph.",
            ["project/alpha"],
        )

        result = self.server.accept_entity_proposals("Projects/Alpha Roadmap", min_confidence=0.6)
        graph = self.server.get_knowledge_graph()

        self.assertEqual(result, "OK: accepted 3 entity proposals from 'Projects/Alpha Roadmap'.")
        self.assertEqual(
            graph["entities"],
            [
                {"name": "Obsidian Vault", "entity_type": "Concept", "observations": []},
                {"name": "knowledge/graph", "entity_type": "Concept", "observations": []},
                {"name": "project/alpha", "entity_type": "Project", "observations": []},
            ],
        )

    def test_accept_entity_proposals_can_link_note_to_accepted_entities(self):
        self.server.create_note("Project Note", "Mentions [[Obsidian Vault]].", None)

        result = self.server.accept_entity_proposals(
            "Project Note",
            min_confidence=0.8,
            link_note=True,
            relation="mentions",
        )

        self.assertEqual(result, "OK: accepted 1 entity proposals from 'Project Note'.")
        self.assertEqual(
            self.server.get_entity_notes("Obsidian Vault"),
            [
                {
                    "entity_name": "Obsidian Vault",
                    "note_title": "Project Note",
                    "note_path": "Project Note.md",
                    "relation": "mentions",
                }
            ],
        )

    def test_accept_entity_proposals_reports_no_candidates(self):
        self.server.create_note("Plain", "no useful candidates", None)

        self.assertEqual(
            self.server.accept_entity_proposals("Plain", min_confidence=0.9),
            "OK: accepted 0 entity proposals from 'Plain'.",
        )

    def test_propose_relations_from_note_returns_candidates_without_storing(self):
        self.server.create_note(
            "Projects/Alpha Roadmap",
            "Discuss [[Obsidian Vault]] and [[Knowledge Graph]].",
            ["project/alpha"],
        )

        proposals = self.server.propose_relations_from_note("Projects/Alpha Roadmap")
        graph = self.server.get_knowledge_graph()

        self.assertEqual(
            proposals,
            [
                {
                    "source": "Alpha Roadmap",
                    "relation": "references",
                    "target": "Knowledge Graph",
                    "evidence": "wiki_link",
                    "confidence": 0.7,
                },
                {
                    "source": "Alpha Roadmap",
                    "relation": "references",
                    "target": "Obsidian Vault",
                    "evidence": "wiki_link",
                    "confidence": 0.7,
                },
            ],
        )
        self.assertEqual(graph, {"entities": [], "relations": []})

    def test_propose_relations_from_note_handles_missing_note(self):
        self.assertEqual(self.server.propose_relations_from_note("Missing"), [])

    def test_extract_with_provider_rule_based_combines_entity_and_relation_proposals(self):
        self.server.create_note(
            "Projects/Alpha Roadmap",
            "Discuss [[Obsidian Vault]] and #project/alpha.",
            None,
        )

        result = self.server.extract_with_provider("Projects/Alpha Roadmap")

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

    def test_extract_with_provider_rejects_unknown_provider(self):
        self.server.create_note("Note", "body", None)

        result = self.server.extract_with_provider("Note", provider="openai")

        self.assertEqual(result["provider"], "openai")
        self.assertEqual(result["entities"], [])
        self.assertEqual(result["relations"], [])
        self.assertIn("unsupported provider", result["error"])

    def test_vault_status_resource_returns_json_summary(self):
        self.server.create_note("Status", "body", None)
        self.server.rebuild_note_index()

        resource = self.server.vault_status_resource()

        self.assertIn('"note_count": 1', resource)
        self.assertIn('"missing_link_count": 0', resource)

    def test_graph_summary_resource_returns_json_summary(self):
        self.server.create_note("A", "[[B]] [[Missing]]", None)
        self.server.create_note("B", "target", None)
        self.server.rebuild_note_index()

        resource = self.server.graph_summary_resource()

        self.assertIn('"node_count": 2', resource)
        self.assertIn('"edge_count": 2', resource)
        self.assertIn('"missing_link_count": 1', resource)

    def test_safe_edit_prompt_mentions_preview_and_backup(self):
        prompt = self.server.safe_edit_prompt("Draft", "refresh the setup section")

        self.assertIn("Draft", prompt)
        self.assertIn("preview", prompt.lower())
        self.assertIn("backup", prompt.lower())

    def test_project_memory_guide_resource_explains_agent_usage(self):
        guide = self.server.project_memory_guide_resource()

        self.assertIn("create_project_workspace", guide)
        self.assertIn("log_project_update", guide)
        self.assertIn("record_project_decision", guide)
        self.assertIn("capture_project_idea", guide)

    def test_project_memory_prompt_mentions_project_tools(self):
        prompt = self.server.project_memory_prompt("obsidian-agent")

        self.assertIn("obsidian-agent", prompt)
        self.assertIn("create_project_workspace", prompt)
        self.assertIn("log_project_update", prompt)
