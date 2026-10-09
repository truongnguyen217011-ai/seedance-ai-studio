import os
import re
import time
from typing import List, Dict, Any, Optional
from database import get_connection, log_event

def parse_all_clip_prompts_file(file_path: str) -> List[Dict[str, Any]]:
    """
    Phân tích file `_ALL_CLIP_PROMPTS.txt` từ bộ khung B3 của TOOL AI:
    Mỗi block có dạng:
    === CLIP 1 ===
    <Nội dung prompt của clip>
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Không tìm thấy file: {file_path}")

    # Nếu người dùng truyền thư mục bài viết (ví dụ: D:\TOOL_AI\Ten_Bai)
    if os.path.isdir(file_path):
        candidate = os.path.join(file_path, "_ALL_CLIP_PROMPTS.txt")
        if os.path.exists(candidate):
            file_path = candidate
        else:
            raise FileNotFoundError(f"Không tìm thấy file _ALL_CLIP_PROMPTS.txt trong thư mục: {file_path}")

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Thư mục chứa bài và thư mục ảnh nhân vật đi kèm
    prod_dir = os.path.dirname(file_path)
    images_dir = os.path.join(prod_dir, "images")

    # Tìm danh sách ảnh nhân vật có sẵn
    avail_images = []
    if os.path.exists(images_dir):
        for fname in os.listdir(images_dir):
            if fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                avail_images.append(os.path.join(images_dir, fname))

    # Tách các clip theo pattern `=== CLIP (\d+) ===`
    pattern = re.compile(r'===\s*CLIP\s*(\d+)\s*===', re.IGNORECASE)
    splits = pattern.split(content)

    clips = []
    if len(splits) > 1:
        # splits[0] là phần trước clip đầu tiên (thường rỗng)
        # splits[1] là số thứ tự clip 1, splits[2] là nội dung prompt 1, v.v.
        for i in range(1, len(splits), 2):
            c_no = int(splits[i])
            c_prompt = splits[i+1].strip()
            
            # Gán ảnh nhân vật (nếu có nhân vật được nhắc đến hoặc ảnh mặc định)
            ref_image = None
            if avail_images:
                # Gán ảnh tương ứng theo thứ tự hoặc ảnh đầu tiên
                ref_image = avail_images[(c_no - 1) % len(avail_images)]

            clips.append({
                "clip_index": c_no,
                "prompt": c_prompt,
                "reference_image": ref_image
            })
    else:
        # Nếu không có header '=== CLIP', tách theo từng dòng không rỗng
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        for idx, line in enumerate(lines, 1):
            clips.append({
                "clip_index": idx,
                "prompt": line,
                "reference_image": avail_images[0] if avail_images else None
            })

    return clips

def import_b3_batch(file_path: str, title: Optional[str] = None) -> Dict[str, Any]:
    """
    Nạp 180 clip từ bài sản xuất của TOOL AI vào CSDL hàng đợi jobs
    và phân bổ đều cho các tài khoản Muse AI sẵn có.
    """
    clips = parse_all_clip_prompts_file(file_path)
    if not clips:
        return {"success": False, "message": "Không tìm thấy clip nào trong file prompt"}

    if not title:
        title = os.path.basename(os.path.dirname(file_path)) or f"Production_{int(time.time())}"

    batch_id = f"BATCH_{int(time.time())}_{len(clips)}"

    # Lấy danh sách tài khoản Muse AI sẵn sàng
    conn = get_connection()
    muse_accounts = conn.execute("""
        SELECT id, name, tokens_balance FROM accounts 
        WHERE (account_type = 'muse' OR account_type IS NULL) 
          AND status = 'ready' 
          AND (tokens_balance > 0 OR tokens_balance IS NULL)
        ORDER BY id ASC
    """).fetchall()

    acc_list = [dict(a) for a in muse_accounts]
    num_accounts = len(acc_list)

    log_event(f"📦 Bắt đầu nạp {len(clips)} clip cho bài '{title}'. Tìm thấy {num_accounts} nick Muse AI sẵn sàng.", "INFO", "Batch")

    inserted_count = 0
    for idx, c in enumerate(clips):
        # Phân chia đều theo cụm phân đoạn (Scene Batch) nếu có nhiều nick
        assigned_acc_id = None
        if num_accounts > 0:
            # Ví dụ: 180 clip chia cho 6 nick -> mỗi nick ~30 clip liên tục
            acc_idx = (idx * num_accounts) // len(clips)
            assigned_acc_id = acc_list[acc_idx]["id"]

        conn.execute("""
            INSERT INTO jobs (
                account_id, title, prompt, model, duration, 
                status, status_message, progress, reference_image, 
                batch_id, clip_index, created_at, updated_at
            ) VALUES (?, ?, ?, 'Muse AI 10s', '10 giây', 'Đang chờ', 'Chờ render', 0, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (
            assigned_acc_id,
            f"{title} - Clip {c['clip_index']:03d}",
            c["prompt"],
            c["reference_image"],
            batch_id,
            c["clip_index"]
        ))
        inserted_count += 1

    conn.commit()
    conn.close()

    msg = f"Đã nạp thành công {inserted_count} clip vào đợt #{batch_id} (chia cho {num_accounts} tài khoản Muse AI)!"
    log_event(msg, "SUCCESS", "Batch")

    return {
        "success": True,
        "batch_id": batch_id,
        "total_clips": inserted_count,
        "accounts_assigned": num_accounts,
        "message": msg
    }

def get_batch_progress(batch_id: str) -> Dict[str, Any]:
    """Kiểm tra tiến độ render của 1 đợt 180 clip"""
    conn = get_connection()
    jobs = conn.execute("SELECT id, clip_index, status, local_video_path FROM jobs WHERE batch_id = ? ORDER BY clip_index ASC", (batch_id,)).fetchall()
    conn.close()

    total = len(jobs)
    if total == 0:
        return {"total": 0, "completed": 0, "percent": 0}

    completed = sum(1 for j in jobs if j["status"] == "Hoàn thành")
    processing = sum(1 for j in jobs if j["status"] == "Đang xử lý")
    failed = sum(1 for j in jobs if j["status"] == "Thất bại")
    pending = sum(1 for j in jobs if j["status"] == "Đang chờ")

    percent = int((completed / total) * 100) if total > 0 else 0

    return {
        "batch_id": batch_id,
        "total": total,
        "completed": completed,
        "processing": processing,
        "failed": failed,
        "pending": pending,
        "percent": percent,
        "is_finished": (completed + failed) == total
    }

