"""agent_cli.py — CLI wrapper for the Media Impact Sales Agent.

Usage:
    python src/agent_cli.py "Ich suche Channels mit hoher Kaufkraft für eine Auto-Kampagne"
    python src/agent_cli.py          # interactive prompt
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make sibling modules importable when run as a script.
sys.path.insert(0, str(Path(__file__).parent))

_DEFAULT_DB = "postgresql://miuser:mipass@127.0.0.1:5433/mediaimpact"
os.environ.setdefault("DATABASE_URL", _DEFAULT_DB)


def _check_env() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Fehler: ANTHROPIC_API_KEY ist nicht gesetzt.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Media Impact Sales Agent — beantwortet Werbeberatungs-Fragen "
                    "auf Basis der Media-Impact-Datenbank.",
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Frage an den Agenten. Wenn leer, wird interaktiv nachgefragt.",
    )
    args = parser.parse_args()

    _check_env()

    if args.query:
        question = " ".join(args.query)
    else:
        print("Frage an den Media Impact Sales Agent (Enter zum Absenden):")
        question = input("> ").strip()
        if not question:
            sys.exit("Keine Frage eingegeben.")

    # Import here so env vars are set before any module-level DB connection.
    from agent import run_agent

    print("\nAgent arbeitet …\n")
    answer = run_agent(question)
    print(answer)


if __name__ == "__main__":
    main()
