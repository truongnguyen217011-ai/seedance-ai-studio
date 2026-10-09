import asyncio
import sys
import time

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from database import get_connection
from dola_service import execute_video_job
from muse_service import execute_muse_job

is_running = True

async def worker_loop():
    """
    Vòng lặp ngầm quét hàng đợi jobs và thực thi song song (hỗ trợ cả Dola AI & Muse AI)
    """
    global is_running
    while is_running:
        try:
            conn = get_connection()
            # Đọc cấu hình số luồng song song tối đa
            setting = conn.execute("SELECT value FROM settings WHERE key = 'max_concurrent_jobs'").fetchone()
            max_concurrent = int(setting["value"]) if setting else 5
            
            # Đếm số job đang chạy
            running_count = conn.execute("SELECT COUNT(*) as count FROM jobs WHERE status = 'Đang chạy'").fetchone()["count"]
            
            available_slots = max_concurrent - running_count
            if available_slots > 0:
                # Lấy các job đang chờ (pending)
                pending_jobs = conn.execute(
                    "SELECT id, model, account_id FROM jobs WHERE status = 'Đang chờ' ORDER BY id ASC LIMIT ?", 
                    (available_slots,)
                ).fetchall()
                
                for job in pending_jobs:
                    # Đánh dấu đang chạy
                    conn.execute("UPDATE jobs SET status = 'Đang chạy', status_message = 'Đang phân luồng...' WHERE id = ?", (job["id"],))
                    conn.commit()

                    # Phân luồng thông minh: Muse AI vs Dola
                    is_muse = False
                    if "muse" in (job["model"] or "").lower():
                        is_muse = True
                    elif job["account_id"]:
                        acc = conn.execute("SELECT account_type FROM accounts WHERE id = ?", (job["account_id"],)).fetchone()
                        if acc and acc["account_type"] == "muse":
                            is_muse = True

                    if is_muse:
                        asyncio.create_task(execute_muse_job(job["id"]))
                    else:
                        asyncio.create_task(execute_video_job(job["id"]))
                    
            # Tự động kết thúc thời gian nghỉ cho tài khoản khi hết hạn rest_until
            conn.execute("""
                UPDATE accounts 
                SET rest_until = NULL, rest_reason = NULL 
                WHERE rest_until IS NOT NULL 
                  AND rest_until <= datetime('now', 'localtime')
            """)

            # Tự động hồi phục tài khoản rate_limited sau 30 phút cooldown
            conn.execute("""
                UPDATE accounts 
                SET status = 'ready' 
                WHERE status = 'rate_limited' 
                  AND (strftime('%s', 'now') - strftime('%s', last_used)) > 1800
            """)
            conn.commit()
            conn.close()
        except Exception as loop_err:
            print(f"[Worker Error] {loop_err}", flush=True)
            try:
                conn.close()
            except Exception:
                pass
        await asyncio.sleep(2)

def start_worker():
    return asyncio.create_task(worker_loop())
