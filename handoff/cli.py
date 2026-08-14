#!/usr/bin/env python3
"""Thin CLI for the agent-handoff skill to invoke storage operations.

Invoked by SKILL.md via bash with absolute paths:
  PYTHONPATH=<repo> python3 <repo>/handoff/cli.py <subcommand> [args]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_pkg_root = str(Path(__file__).resolve().parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from handoff.storage import (
    archive_handoff,
    cleanup_retention,
    get_project_slug,
    list_pending,
    load_config,
    load_handoff,
    save_handoff,
)


def cmd_slug(args):
    print(get_project_slug(args.cwd))


def cmd_save(args):
    content = sys.stdin.read()
    config = load_config()
    filename = save_handoff(args.slug, content, args.semantic)
    cleanup_retention(args.slug, config)
    print(json.dumps({"filename": filename, "slug": args.slug}))


def cmd_list(args):
    pending = list_pending(args.slug)
    print(json.dumps({"slug": args.slug, "pending": pending}))


def cmd_load(args):
    content = load_handoff(args.slug, args.file)
    print(content)


def cmd_archive(args):
    archive_handoff(args.slug, args.file)
    print(json.dumps({"archived": args.file, "slug": args.slug}))


def main():
    parser = argparse.ArgumentParser(description="Handoff storage CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_slug = sub.add_parser("slug")
    p_slug.add_argument("--cwd", required=True)
    p_slug.set_defaults(func=cmd_slug)

    p_save = sub.add_parser("save")
    p_save.add_argument("--slug", required=True)
    p_save.add_argument("--semantic", default="handoff")
    p_save.set_defaults(func=cmd_save)

    p_list = sub.add_parser("list")
    p_list.add_argument("--slug", required=True)
    p_list.set_defaults(func=cmd_list)

    p_load = sub.add_parser("load")
    p_load.add_argument("--slug", required=True)
    p_load.add_argument("--file", required=True)
    p_load.set_defaults(func=cmd_load)

    p_archive = sub.add_parser("archive")
    p_archive.add_argument("--slug", required=True)
    p_archive.add_argument("--file", required=True)
    p_archive.set_defaults(func=cmd_archive)

    parsed = parser.parse_args()
    parsed.func(parsed)


if __name__ == "__main__":
    main()
