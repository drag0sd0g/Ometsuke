"""Command line: run, replay, score, list."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import dataset, db, prompts, runner

DEFAULT_DB = pathlib.Path("data/runs.sqlite")


def _model(name: str, host: str, timeout_s: float):
    """`stub` for offline path exercise; anything else is a local model tag.

    There is no remote branch here by design: every run this project reports is produced
    on local weights, and the digest of those weights is recorded with it.
    """
    if name == "stub":
        from .model import StubModel

        return StubModel()
    from .ollama import OllamaError, OllamaModel

    try:
        return OllamaModel(tag=name, host=host, timeout_s=timeout_s)
    except OllamaError as exc:
        raise SystemExit(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ometsuke", description=__doc__)
    parser.add_argument("--db", type=pathlib.Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="record a run against a split")
    run.add_argument("--split", default="dev", choices=["dev", "train", "test"])
    run.add_argument("--model", default="ometsuke-eval",
                     help="a local model tag, or 'stub' to exercise the path offline")
    run.add_argument("--limit", type=int)
    run.add_argument("--host", default="http://localhost:11434")
    run.add_argument("--timeout", type=float, default=600,
                     help="seconds per call; the longest filings need ~80s of prefill alone")
    run.add_argument("--prompt", default="baseline",
                     help="prompt variant; 'baseline' is the control")
    run.add_argument("--pairs", metavar="JSONL",
                     help="score two-year section pairs from this file instead of a "
                          "dataset split (see scripts/extract_sections.py)")
    run.add_argument("--sheets", default=",".join(prompts.DEFAULT_SHEETS),
                     help="comma-separated fields to put in the prompt; 'text' is the "
                          "narrative report. 'meta' is refused — it carries the filing date")

    replay = sub.add_parser("replay", help="re-derive predictions from a recorded run")
    replay.add_argument("run_id")
    replay.add_argument("--rescore", action="store_true",
                        help="declare that parsing or scoring code has changed")

    score = sub.add_parser("score", help="metrics with company-clustered intervals")
    score.add_argument("run_id")
    score.add_argument("--split", default="dev", choices=["dev", "train", "test"])
    score.add_argument("--allow-failures", action="store_true")
    score.add_argument("--draws", type=int, default=2000)

    dist = sub.add_parser("distribution",
                          help="how each run spends the score range (judge prompts on this)")
    dist.add_argument("run_id", nargs="+")
    dist.add_argument("--split", default="dev", choices=["dev", "train", "test"])

    sub.add_parser("runs", help="list runs")

    args = parser.parse_args(argv)
    conn = db.connect(args.db)

    if args.command == "run" and args.pairs:
        import json as _json
        pairs = [_json.loads(line) for line in pathlib.Path(args.pairs).open(encoding="utf-8")]
        pairs = [p for p in pairs if not p["sections_missing"]]
        if args.limit:
            pairs = pairs[: args.limit]
        model = _model(args.model, args.host, args.timeout)
        try:
            build = prompts.pair_builder(args.prompt)
        except KeyError as exc:
            raise SystemExit(str(exc)) from exc
        run_id = runner.record(conn, pairs, model, build,
                               split=args.split,
                               dataset_ver=f"section-pairs:{pathlib.Path(args.pairs).name}",
                               config={**getattr(model, "config", dict)(),
                                       **prompts.config(args.prompt),
                                       "source": "section-pairs", "n_pairs": len(pairs)})
        print(run_id)

    elif args.command == "run":
        rows = dataset.load(args.split, limit=args.limit)
        source = "train" if args.split == "dev" else args.split
        prov = dataset.provenance(source)
        model = _model(args.model, args.host, args.timeout)
        try:
            sheets = prompts.sheets_from(args.sheets)
            build = prompts.builder(args.prompt, sheets=sheets)
        except (KeyError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        run_id = runner.record(conn, rows, model, build,
                               split=args.split,
                               dataset_ver=dataset.version_string(prov),
                               config={**getattr(model, "config", dict)(),
                                       **prompts.config(args.prompt, sheets)},
                               provenance=prov)
        print(run_id)

    elif args.command == "replay":
        print(runner.replay(conn, args.run_id, mode="rescore" if args.rescore else "replay"))

    elif args.command == "score":
        rows = dataset.load(args.split)
        result = runner.score(conn, args.run_id, dataset.truth(rows),
                              groups=dataset.groups(rows),
                              allow_failures=args.allow_failures, draws=args.draws)
        print(json.dumps(result, indent=2))

    elif args.command == "distribution":
        truth = dataset.truth(dataset.load(args.split))
        for run_id in args.run_id:
            report = runner.distribution(conn, run_id, truth)
            print(json.dumps(report, indent=2, ensure_ascii=False))

    elif args.command == "runs":
        for row in conn.execute(
            "SELECT run_id, split, started_at, finished_at FROM runs ORDER BY started_at"
        ):
            state = "done" if row["finished_at"] else "open"
            print(f"{row['run_id']}  {row['split']:<5}  {row['started_at'][:19]}  {state}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
