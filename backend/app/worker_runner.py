"""Queued worker: processes experiments whose trials are still queued.
Local mode (default) polls the same DB the API uses — no Redis required.
Production: put this behind Redis/RQ or Celery; the executor contract is unchanged.
Usage: PYTHONPATH=backend python3 -m app.worker_runner --once | --poll 5"""
import argparse
import time

from . import models
from .database import SessionLocal, init_db
from .execution import run_experiment
from .seed import seed


def pending_experiment_ids(db):
    rows = db.query(models.Trial.experiment_id).filter(models.Trial.status == "queued").distinct().all()
    return [r[0] for r in rows]

def run_once(db) -> list[int]:
    done = []
    for exp_id in pending_experiment_ids(db):
        exp = db.get(models.Experiment, exp_id)
        if exp and exp.status in ("created", "queued", "running", "failed"):
            exp.status = "queued"; db.commit()
            run_experiment(db, exp); done.append(exp_id)
    return done

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll", type=float, default=0, help="seconds between polls (0 = run once)")
    args = ap.parse_args()
    init_db(); db = SessionLocal(); seed(db)
    try:
        while True:
            done = run_once(db)
            print(f"worker processed experiments: {done}", flush=True)
            if args.once or not args.poll: break
            time.sleep(args.poll)
    finally:
        db.close()

if __name__ == "__main__":
    main()
