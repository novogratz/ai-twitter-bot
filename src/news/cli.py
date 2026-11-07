"""Manual runs, an hourly scheduler and explicit draft acknowledgement."""
import argparse
from datetime import datetime
import json
import time

from ..core import settings

from . import history
from .adapters import HTTP
from .config import load
from .editor import TZ
from .pipeline import retry_pending, run
from .store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verified news; Safari only with NEWS_AUTO_PUBLISH opt-in, no email")
    parser.add_argument("--config", help="Account news TOML override")
    parser.add_argument("--dry-run", action="store_true", help="Show configuration only; no reads/models/delivery")
    parser.add_argument("--prepare-only", action="store_true", help="Run discovery/review and leave approved picks pending for the bot's delivery worker")
    parser.add_argument("command", choices=("run", "serve", "status", "check-sources", "import-history", "ack"))
    parser.add_argument("delivery_id", nargs="?")
    args = parser.parse_args(argv)
    cfg = load(args.config)
    if args.prepare_only and args.command != "run":
        parser.error("--prepare-only is only valid with run")
    if args.dry_run:
        print(json.dumps({"timezone": "America/Toronto", "interval_hours": 1, "delivery": cfg.delivery_adapter,
            "search": cfg.search_adapter, "source_count": len(cfg.sources), "automatic_x": settings.get("NEWS_AUTO_PUBLISH"),
            "news_email": False, "max_picks": 2, "empty_runs": "silent", "prompt": cfg.prompt_file}, indent=2))
        return
    if args.command == "serve":
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.executors.pool import ThreadPoolExecutor
        from apscheduler.triggers.interval import IntervalTrigger
        scheduler = BlockingScheduler(timezone=TZ, executors={"default": ThreadPoolExecutor(1)})
        scheduler.add_job(run, IntervalTrigger(hours=1, timezone=TZ), kwargs={"cfg": cfg},
                          id="news_discovery", max_instances=1, coalesce=True, misfire_grace_time=3600,
                          next_run_time=datetime.now(TZ))
        scheduler.add_job(retry_pending, IntervalTrigger(minutes=1, timezone=TZ), kwargs={"cfg": cfg},
                          id="news_delivery", max_instances=1, coalesce=True, misfire_grace_time=60)
        scheduler.start()
        return
    store = Store()
    if args.command == "run":
        # Empty or held runs produce no stdout and no destination message.
        delivery = None
        if args.prepare_only:
            from .adapters import PendingDelivery
            delivery = PendingDelivery()
        for payload in run(cfg, store=store, delivery=delivery):
            print(payload["display"] + "\n")
    elif args.command == "ack":
        if not args.delivery_id:
            parser.error("ack requires a delivered draft ID")
        store.acknowledge(args.delivery_id, time.time())
        print("Acknowledged " + args.delivery_id)
    elif args.command == "status":
        print(json.dumps({"runs": store.rows("SELECT * FROM runs ORDER BY started DESC LIMIT 5"),
                          "outbox": store.rows("SELECT id,state,attempts,acknowledged,error FROM outbox ORDER BY due DESC LIMIT 20"),
                          "coverage": store.rows("SELECT * FROM coverage"),
                          "costs": store.rows("SELECT * FROM costs ORDER BY day DESC LIMIT 9")}, indent=2))
    elif args.command == "import-history":
        with store.lock():
            history.context(store, cfg, time.time())
        print("Imported accessible history; status reports missing or incomplete coverage.")
    elif args.command == "check-sources":
        now = time.time()
        http = HTTP(store, cfg, now)
        failed = False
        for source in cfg.sources:
            try:
                leads = http.discover(source)
                print(json.dumps({"source": source["name"], "url": source["url"], "read": True, "leads": len(leads)}))
            except Exception as exc:
                failed = True
                print(json.dumps({"source": source["name"], "read": False, "error": type(exc).__name__}))
        if failed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
