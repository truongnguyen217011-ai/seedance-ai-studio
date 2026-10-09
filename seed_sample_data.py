import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "studio.db")

def seed():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Thêm ảnh mẫu
    cursor.execute("SELECT COUNT(*) FROM images")
    if cursor.fetchone()[0] == 0:
        sample_images = [
            (1, "Chân dung nữ điệp viên trong đêm mưa neon cyberpunk, ánh sáng volumetric, cinematic 8k", "Seedance Image 2.5", "16:9", "Cinematic", "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=600"),
            (2, "Đấu sĩ samurai đứng trên đỉnh vách núi hoa anh đào bay, phong cách anime Shonen u ám", "Seedance Image 2.5", "9:16", "Anime", "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600"),
            (3, "Chiếc xe thể thao cổ điển lướt qua đường cao tốc ven biển hoàng hôn vàng", "Seedance Image 2.5", "16:9", "Realistic", "https://images.unsplash.com/photo-1503376780353-7e6692767b70?w=600"),
            (4, "Robot phục vụ cà phê trong quán trà tương lai ở Tokyo", "Seedance Image 2.5", "1:1", "3D Render", "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=600")
        ]
        cursor.executemany("""
            INSERT INTO images (account_id, prompt, model, aspect_ratio, style, image_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, sample_images)

    # 2. Thêm nhân vật & asset mẫu
    cursor.execute("SELECT COUNT(*) FROM assets")
    if cursor.fetchone()[0] == 0:
        sample_assets = [
            ("Tiểu Vũ (Cyberpunk Heroine)", "CHAR_TV_01", "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400", "Nữ sát thủ tóc ngắn bạch kim, mắt xanh neon, áo khoác da đen", "nữ, cyberpunk, hành động"),
            ("Hàn Phong (Kiếm Khách Cổ Trang)", "CHAR_HP_02", "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400", "Kiếm sĩ áo bào trắng, tóc dài búi ngọc, phong thái lạnh lùng", "nam, cổ trang, kiếm hiệp"),
            ("Alex (Doanh Nhân Trẻ)", "CHAR_AX_03", "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400", "Nam thanh niên 28 tuổi, vest xám sang trọng, đồng hồ kim loại", "nam, hiện đại, thương mại")
        ]
        cursor.executemany("""
            INSERT INTO assets (name, character_code, image_url, description, tags)
            VALUES (?, ?, ?, ?, ?)
        """, sample_assets)

    # 3. Thêm nhật ký mẫu
    cursor.execute("SELECT COUNT(*) FROM system_logs")
    if cursor.fetchone()[0] == 0:
        sample_logs = [
            ("INFO", "Engine", "Khởi động Seedance AI Studio v1.0.127 thành công."),
            ("SUCCESS", "Proxy", "Kiểm tra 5 proxy: 5/5 proxy hoạt động tốt (Ping ~85ms)."),
            ("INFO", "Account", "Tải danh sách 5 tài khoản Facebook Clone sẵn sàng."),
            ("SUCCESS", "Dola", "Phiên đăng nhập Dola AI hoạt động bình thường trên các profile."),
            ("INFO", "Queue", "Đang xử lý 3 jobs tạo video song song...")
        ]
        cursor.executemany("""
            INSERT INTO system_logs (level, module, message)
            VALUES (?, ?, ?)
        """, sample_logs)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    seed()
