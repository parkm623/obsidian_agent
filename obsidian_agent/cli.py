import argparse
import json
import sys
from collections.abc import Callable


Operation = Callable[..., object]


def print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cli_main(operations: dict[str, Operation], argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the Obsidian Agent index and graph.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("rebuild", help="Rebuild the note index from scratch.")
    subparsers.add_parser("sync", help="Synchronize changed notes into the index.")

    search_parser = subparsers.add_parser("search", help="Search indexed notes.")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)

    graph_parser = subparsers.add_parser("graph", help="Print the indexed note graph as JSON.")
    graph_parser.add_argument("--resolved-only", action="store_true")

    subparsers.add_parser("knowledge-graph", help="Print the curated knowledge graph as JSON.")
    subparsers.add_parser("export-kg", help="Export the curated knowledge graph as JSON.")
    subparsers.add_parser("missing-links", help="Print unresolved wiki links as JSON.")
    subparsers.add_parser("orphans", help="Print orphan notes as JSON.")
    subparsers.add_parser("status", help="Print vault and index status as JSON.")

    args = parser.parse_args(argv)

    if args.command == "rebuild":
        print(operations["rebuild"]())
    elif args.command == "sync":
        print(operations["sync"]())
    elif args.command == "search":
        print_json(operations["search"](args.query, limit=args.limit))
    elif args.command == "graph":
        print_json(operations["graph"](include_unresolved=not args.resolved_only))
    elif args.command == "knowledge-graph":
        print_json(operations["knowledge_graph"]())
    elif args.command == "export-kg":
        print_json(operations["export_knowledge_graph"]())
    elif args.command == "missing-links":
        print_json(operations["missing_links"]())
    elif args.command == "orphans":
        print_json(operations["orphans"]())
    elif args.command == "status":
        print_json(operations["status"]())
    else:
        parser.error(f"unknown command: {args.command}")

    return 0


def cli_entry(operations: dict[str, Operation]) -> int:
    return cli_main(operations, sys.argv[1:])
