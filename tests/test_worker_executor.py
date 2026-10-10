"""
BH-32: job chạy trên worker.JOB_EXECUTOR riêng; executor mặc định của asyncio (nhỏ: cpu + 4) phải còn chỗ
cho vòng quét `_tick`, `find_chrome` và `/api/health` trong lúc 6 Chrome đang render.

Giả lập máy 1 nhân (os.cpu_count = 1 → executor mặc định 5 thread): nếu job vẫn chạy bằng asyncio.to_thread,
6 job sẽ chiếm hết và worker_alive() về False.
"""
from __future__ import annotations

import os
import threading
import time

import pytest

from constants import JobStatus
from _helpers import wait_jobs_finished, wait_until

pytestmark = [pytest.mark.integration, pytest.mark.timeout(180)]

worker = pytest.importorskip("worker", reason="worker.py chưa có")
fastapi_testclient = pytest.importorskip("fastapi.testclient", reason="cần fastapi + httpx (requirements-dev.txt)")


def test_bh32_job_executor_configuration():
    from concurrent.futures import ThreadPoolExecutor
    assert isinstance(worker.JOB_EXECUTOR, ThreadPoolExecutor)
    assert worker.JOB_EXECUTOR._max_workers == 32
    src = open(worker.__file__, encoding="utf-8").read()
    assert "to_thread(execute_video_job" not in src, "BH-32: job không được chạy trên executor mặc định"
    assert "run_in_executor(JOB_EXECUTOR" in src


def test_bh32_health_responsive_while_jobs_run(db, fake_dola, monkeypatch, worker_runner):
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    monkeypatch.setattr(os, "process_cpu_count", lambda: 1, raising=False)
    db.set_setting("max_concurrent_jobs", 6)
    fake_dola.control(render_seconds=8, credits=10)
    acc_ids = [db.add_account(f"nick{i + 1}") for i in range(6)]
    job_ids = [db.add_job(f"BH-32 job {i + 1}") for i in range(6)]

    import app as app_module
    client = fastapi_testclient.TestClient(app_module.app)

    worker_runner.start()
    wait_until(lambda: len(db.running_jobs()) == 6, 60, what="6 job Đang chạy cùng lúc")

    # Vòng quét phải tiếp tục chạy (2 s/lần) trong lúc 6 job render ≥ 8 s. Nếu job chiếm executor mặc định
    # (5 thread khi cpu_count = 1), `_tick` xếp hàng sau job thứ 6 và `_last_tick` đứng yên hơn 8 s.
    t0 = worker._last_tick
    wait_until(lambda: worker._last_tick > t0, 6, what="vòng quét worker tiếp tục chạy khi 6 job đang render (BH-32)")

    samples = []
    for _ in range(4):
        t0 = time.monotonic()
        r = client.get("/api/health")
        dt = time.monotonic() - t0
        assert r.status_code == 200, r.text
        samples.append((dt, r.json()["worker_alive"], worker.worker_alive()))
        time.sleep(0.5)
    slow = [s for s in samples if s[0] >= 2.0]
    assert not slow, f"/api/health chậm hơn 2 s trong lúc job chạy: {samples}"
    dead = [s for s in samples if not (s[1] and s[2])]
    assert not dead, f"worker_alive False trong lúc job chạy (BH-32: job chiếm executor mặc định): {samples}"
    job_threads = [t.name for t in threading.enumerate() if t.name.startswith("job")]
    assert job_threads, "không thấy thread tên 'job*': job không chạy trên JOB_EXECUTOR"

    jobs = wait_jobs_finished(db, job_ids, 150)
    bad = {jid: (j["status"], j["status_message"]) for jid, j in jobs.items() if j["status"] != JobStatus.HOAN_THANH}
    assert not bad, bad
    assert {j["account_id"] for j in jobs.values()} == set(acc_ids)
    wait_until(lambda: all(db.account(a)["busy_job_id"] is None for a in acc_ids), 30, what="mọi nick được trả")
