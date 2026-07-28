from __future__ import annotations

import argparse
import sys

from scanner.worker_runtime import RailwayShadowWorker, WorkerConfig, log_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drew Tennis Scanner Railway shadow worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run exactly one scan cycle, print the summary, and exit.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate environment variables and Supabase tables, then exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = WorkerConfig.from_env()
        worker = RailwayShadowWorker(config)
        if args.check_config:
            worker.verify_startup()
            log_json("config_check_passed", config=config.public_summary())
            return 0
        if args.once:
            worker.verify_startup()
            report = worker.run_cycle()
            log_json("one_cycle_complete", cycle_id=report.cycle_id, status=report.status, **report.metrics())
            return 0 if report.status in {"SUCCESS", "DEGRADED"} else 1
        worker.run_forever()
        return 0
    except Exception as exc:
        log_json("worker_startup_failed", error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
