"""Command line: run, replay, score, list."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import dataset, db, prompts, runner

DEFAULT_DB = pathlib.Path("data/runs.sqlite")


def _model(name: str):
    if name == "stub":
        from .model import StubModel

        return StubModel()
    raise SystemExit(
        f"unknown model {name!r}. Only 'stub' is wired up; the Anthropic client lands "
        "with the first recorded run."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ometsuke", description=__doc__)
    parser.add_argument("--db", type=pathlib.Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="record a run against a split")
    run.add_argument("--split", default="dev", choices=["dev", "train", "test"])
    run.add_argument("--model", default="stub")
    run.add_argument("--limit", type=int)

    replay = sub.add_parser("replay", help="re-derive predictions from a recorded run")
    replay.add_argument("run_id")
    replay.add_argument("--rescore", action="store_true",
                        help="declare that parsing or scoring code has changed")

    score = sub.add_parser("score", help="metrics with company-clustered intervals")
    score.add_argument("run_id")
    score.add_argument("--split", default="dev", choices=["dev", "train", "test"])
    score.add_argument("--allow-failures", action="store_true")
    score.add_argument("--draws", type=int, default=2000)

    sub.add_parser("runs", help="list runs")

    args = parser.parse_args(argv)
    conn = db.connect(args.db)

    if args.command == "run":
        rows = dataset.load(args.split, limit=args.limit)
        run_id = runner.record(conn, rows, _model(args.model), prompts.build,
                               split=args.split, dataset_ver=dataset.REPO)
        print(run_id)

    elif args.command == "replay":
        print(runner.replay(conn, args.run_id, mode="rescore" if args.rescore else "replay"))

    elif args.command == "score":
        rows = dataset.load(args.split)
        result = runner.score(conn, args.run_id, dataset.truth(rows),
                              groups=dataset.groups(rows),
                              allow_failures=args.allow_failures, draws=args.draws)
        print(json.dumps(result, indent=2))

    elif args.command == "runs":
        for row in conn.execute(
            "SELECT run_id, split, started_at, finished_at FROM runs ORDER BY started_at"
        ):
            state = "done" if row["finished_at"] else "open"
            print(f"{row['run_id']}  {row['split']:<5}  {row['started_at'][:19]}  {state}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
