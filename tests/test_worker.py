import threading
import time

from echo_os.echo.pipeline import EchoJob
from echo_os.echo.worker import EchoWorker


def test_worker_processes_jobs_in_order_and_survives_errors():
    seen, done = [], threading.Event()

    def process(job):
        seen.append(job.session_id)
        if job.session_id == "boom":
            raise RuntimeError("bad")
        if len(seen) == 3:
            done.set()

    worker = EchoWorker(process, settle_seconds=0)
    worker.start()
    now = time.time()
    for sid in ("a", "boom", "c"):
        worker.submit(EchoJob(sid, "/t", ended_at=now, queued_at=now))
    assert done.wait(2)
    worker.stop()
    assert seen == ["a", "boom", "c"]


def test_worker_waits_out_the_settle_delay():
    slept = []
    worker = EchoWorker(lambda job: None, settle_seconds=1.5, sleep=slept.append)
    worker._handle(EchoJob("a", "/t", ended_at=0, queued_at=time.time()))
    assert 1.0 < slept[0] <= 1.5
