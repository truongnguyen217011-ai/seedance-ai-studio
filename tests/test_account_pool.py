"""
AccountPool: chọn nick, khóa nick, tóm tắt lý do (docs/KIEN_TRUC.md mục 1.2, 2; BH-03).
Tên hàm/lớp lấy qua tests/_helpers.py để sau chỉ sửa một chỗ.
"""
import pytest

from constants import NeedsManual
from _helpers import (TODAY, future_ts, get_pool, pool_acquire, pool_is_busy, pool_release, pool_reset,
                      select_account)

account_pool = pytest.importorskip("account_pool", reason="account_pool.py chưa có")


@pytest.fixture
def pool(db):
    p = get_pool()
    pool_reset(p)
    yield p
    pool_reset(p)


def _job(db, account_id=None):
    jid = db.add_job(account_id=account_id)
    return db.job(jid)


def test_eligible_account_is_selected(db, pool):
    acc_id = db.add_account("nick A")
    acc, summary = select_account(pool, _job(db))
    assert acc is not None and acc["id"] == acc_id
    assert isinstance(summary, str)


def test_no_account_gives_none_and_summary(db, pool):
    acc, summary = select_account(pool, _job(db))
    assert acc is None
    assert summary and isinstance(summary, str)


def test_busy_account_not_selected(db, pool):
    acc_id = db.add_account("nick bận")
    assert pool_acquire(pool, acc_id, job_id=1)
    acc, summary = select_account(pool, _job(db))
    assert acc is None, f"nick đang bận vẫn được chọn: {acc}"
    assert "1 nick đang bận" in summary, summary


def test_summary_counts_groups(db, pool):
    db.add_account("hết credit", credits=0, credits_date=TODAY)
    db.add_account("hết credit 2", credits=0, credits_date=TODAY)
    db.add_account("chưa login", with_session=False)
    busy = db.add_account("đang bận")
    db.add_account("captcha", needs_manual=NeedsManual.CAPTCHA)
    assert pool_acquire(pool, busy, job_id=7)

    acc, summary = select_account(pool, _job(db))
    assert acc is None
    assert "2 nick hết credit" in summary, summary
    assert "1 nick chưa đăng nhập Dola" in summary, summary
    assert "1 nick đang bận" in summary, summary
    assert "1 nick cần kéo captcha" in summary, summary


def test_resting_and_captcha_and_disabled_accounts_not_selected(db, pool):
    db.add_account("đang nghỉ", rest_until=future_ts(60), rest_reason="Hết lượt trong ngày")
    db.add_account("captcha", needs_manual=NeedsManual.CAPTCHA)
    db.add_account("tắt", ready=False)
    db.add_account("không session", with_session=False)
    acc, summary = select_account(pool, _job(db))
    assert acc is None, acc
    assert summary


def test_expired_session_cookie_counts_as_not_logged_in(db, pool):
    db.add_account("hết hạn", cookies=db.fake_cookies("fake-expired", days=-1))
    acc, summary = select_account(pool, _job(db))
    assert acc is None
    assert "chưa đăng nhập Dola" in summary, summary


def test_acquire_twice_same_account_second_is_false(db, pool):
    acc_id = db.add_account()
    assert pool_acquire(pool, acc_id, job_id=1) is True
    assert pool_acquire(pool, acc_id, job_id=2) is False
    assert pool_acquire(pool, acc_id, job_id=1) is False  # cùng job cũng không được giữ hai lần
    assert pool_is_busy(pool, acc_id)
    assert db.account(acc_id)["busy_job_id"] == 1  # cột để UI nhìn thấy


def test_release_then_acquire_again(db, pool):
    acc_id = db.add_account()
    assert pool_acquire(pool, acc_id, job_id=1)
    pool_release(pool, acc_id, 1)
    assert not pool_is_busy(pool, acc_id)
    assert db.account(acc_id)["busy_job_id"] is None
    assert pool_acquire(pool, acc_id, job_id=2)
    pool_release(pool, acc_id, 2)


def test_release_unknown_account_is_harmless(db, pool):
    pool_release(pool, 9999, 1)
    assert not pool_is_busy(pool, 9999)


def test_prefers_account_already_assigned_to_job(db, pool):
    first = db.add_account("nick 1", credits=5, credits_date=TODAY)
    second = db.add_account("nick 2", credits=1, credits_date=TODAY)
    acc, _ = select_account(pool, _job(db, account_id=second))
    assert acc["id"] == second
    acc, _ = select_account(pool, _job(db, account_id=first))
    assert acc["id"] == first


def test_assigned_but_busy_account_falls_back_to_other(db, pool):
    first = db.add_account("nick 1")
    second = db.add_account("nick 2")
    assert pool_acquire(pool, second, job_id=1)
    acc, summary = select_account(pool, _job(db, account_id=second))
    assert acc["id"] == first
    assert "đang bận" in summary


def test_excluded_account_is_skipped(db, pool):
    first = db.add_account("nick 1")
    second = db.add_account("nick 2")
    acc, _ = select_account(pool, _job(db), excluded={first})
    assert acc["id"] == second


def test_two_jobs_get_two_different_accounts(db, pool):
    a = db.add_account("nick 1")
    b = db.add_account("nick 2")
    acc1, _ = select_account(pool, _job(db))
    assert pool_acquire(pool, acc1["id"], job_id=1)
    acc2, _ = select_account(pool, _job(db))
    assert acc2 is not None and acc2["id"] != acc1["id"]
    assert {acc1["id"], acc2["id"]} == {a, b}
