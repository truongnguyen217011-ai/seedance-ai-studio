# Bộ mẫu Đạo diễn AI: 30 prompt mẫu và kết quả ghép (P7)

File này do `python tests/gen_dao_dien_mau.py` sinh ra từ `director.py` (không sửa tay; sửa bộ mẫu thì chạy lại script).
Mục đích: người dùng duyệt xem tool ghép mẫu đạo diễn vào prompt của mình **trước khi gửi Dola** có đúng ý không.

## Cách ghép

```
Tạo video {model} dài {N} giây, tỷ lệ khung hình {tỷ lệ} (dọc|ngang). Không hỏi lại, tạo video ngay.
{prompt gốc nguyên văn, chỉ bỏ số thứ tự đầu dòng}.
Nhân vật: {tên}: {mô tả đã lưu trong Kho nhân vật}; ...
Hình ảnh: {trường phái}; {cỡ cảnh}; {góc máy}; {ống kính}; {ánh sáng}; {bảng màu}; {6 thành tố}.
```

- N là số giây đã ép vào khoảng Dola hỗ trợ 4-15 ("30 giây" cũ → 15); tỷ lệ 16:9 (ngang, mặc định) hoặc 9:16 (dọc). Câu mở đầu nêu rõ cả ba tham số để Dola không hỏi lại (BH-46).
- Lớp nào prompt đã tự mô tả (có `ống kính 85mm`, `cận cảnh`, `ánh sáng ...`, `FPV`, `bảng màu`...) thì **không chèn lại** (P3).
- Lớp tắt trong Cài đặt → Đạo diễn AI thì không chèn (P6). Tắt hẳn Đạo diễn AI → chỉ còn câu mở đầu + prompt gốc.
- Trường phái: tự nhận diện theo từ khóa (bảng dưới), hoặc ép bằng ô "Trường phái" khi nạp lô / Cài đặt.
- **Không còn** câu cố định "FPV ... Hollywood bom tấn" của bản cũ; cảnh đối thoại được nhánh T1 (over-the-shoulder, 85mm, ánh sáng mềm).

## Bộ trường phái (thứ tự ưu tiên nhận diện từ trên xuống)

Bản JS cũ thiếu nhánh **đối thoại** (cảnh hai người nói chuyện bị gán mặc định Cine-Master, rồi backend nối thêm câu FPV hành động). Nhánh **T1** được thêm với từ khóa `nói`, `đối thoại`, `trò chuyện`, `hỏi`, `trả lời`, `dialogue`, `talk`, `conversation` và đặt **đầu** danh sách: cảnh có người nói chuyện thì ngữ pháp máy quay (over-the-shoulder, 85mm, ánh sáng mềm) quan trọng hơn bối cảnh. Muốn giữ bối cảnh (ví dụ W1 viễn tây) thì chọn trường phái tay.

| Mã | Tên | Từ khóa nhận diện |
| --- | --- | --- |
| T1 | Đối Thoại & Trò Chuyện (Over-the-shoulder, 85mm, ánh sáng mềm) | `nói`, `đối thoại`, `trò chuyện`, `hỏi`, `trả lời`, `dialogue`, `talk`, `talking`, `conversation` |
| P1-Macro | Chân Dung Chi Tiết Biểu Cảm (Micro Detail) | `mắt`, `nước mắt`, `nhẫn`, `vết sẹo`, `ngón tay`, `chi tiết`, `vũ khí cận`, `eye`, `eyes`, `macro`, `detail`, `tear`, `tears`, `ring`, `iris` |
| F1 | Fantasy Cổ Tích & Thiên Nhiên (Alan Lee & John Howe) | `rừng`, `cổ tích`, `tiên`, `lâu đài`, `tòa tháp`, `ngọn tháp`, `tháp cổ`, `cây cổ thụ`, `rừng cây`, `tán cây`, `gốc cây`, `suối`, `rêu`, `yêu tinh`, `thung lũng`, `thần thoại`, `hoa cỏ`, `forest`, `castle`, `fantasy`, `ancient`, `fairytale`, `elf`, `woods`, `mossy` |
| F2 | Fantasy Kịch Tính & Hắc Ám (Frank Frazetta & Aleksi Briclot) | `chiến binh`, `quái vật`, `ngọn lửa`, `phun lửa`, `lửa cháy`, `bốc cháy`, `dung nham`, `hắc ám`, `đánh nhau`, `chiến đấu`, `thanh kiếm`, `đấu kiếm`, `đao kiếm`, `vung kiếm`, `cầm kiếm`, `kiếm sĩ`, `vung đao`, `đại đao`, `thanh đao`, `rồng`, `ma vương`, `sát thủ`, `chém`, `huyết`, `warrior`, `monster`, `fire`, `dragon`, `dark`, `battle`, `sword`, `swords`, `frazetta` |
| C1 | Không Gian Lớn & Ánh Màu (Alena Aenami & John Harris) | `vũ trụ`, `hành tinh`, `ngân hà`, `phi thuyền`, `không gian`, `mênh mông`, `hoàng hôn`, `chân trời`, `bầu trời`, `thiên hà`, `vô tận`, `cô độc`, `space`, `galaxy`, `planet`, `cosmic`, `horizon`, `nebula`, `twilight`, `colossal` |
| C2 | Khoa Học Viễn Tưởng Mô-đun & Cơ Khí (Syd Mead & Chris Foss) | `robot`, `máy móc`, `cơ khí`, `công nghệ`, `tương lai`, `mô-đun`, `sci-fi`, `cyborg`, `cyberpunk`, `neon`, `giáp sắt`, `người máy`, `mecha`, `android`, `future`, `high-tech` |
| E1 | Bi Kịch & Lịch Sử Hùng Tráng (Ilya Repin & Gustave Doré) | `lịch sử`, `bi kịch`, `chiến tranh`, `vua`, `hoàng gia`, `đau khổ`, `tang thương`, `thánh đường`, `giáo đường`, `triều đình`, `quân đội`, `thập tự`, `historical`, `history`, `tragedy`, `royal`, `sorrow`, `baroque`, `repin`, `dore` |
| W1 | Miền Tây & Phiêu Lưu Thám Hiểm (Frederic Remington & Frank Schoonover) | `miền tây`, `cao bồi`, `sa mạc`, `ngựa`, `cát bụi`, `hẻm núi`, `hoang dã`, `súng`, `thảo nguyên`, `thám hiểm`, `khám phá`, `western`, `cowboy`, `desert`, `dust`, `canyon`, `horse`, `frontier`, `remington` |
| G1 | Đồ Họa Đường Nét & Mảng Phẳng (Moebius & Kilian Eng) | `anime`, `manga`, `hoạt hình`, `đồ họa`, `truyện tranh`, `vector`, `mảng phẳng`, `vẽ nét`, `moebius`, `comic`, `graphic`, `lineart`, `cartoon`, `illustration` |
| D1 | Gothic U Tối & Sinh Cơ Khí (H.R. Giger & Zdzisław Beksiński) | `ma quái`, `gothic`, `kinh dị`, `u tối`, `xương`, `sinh học`, `quái dị`, `chết chóc`, `ác mộng`, `địa ngục`, `giger`, `beksinski`, `alien`, `horror`, `eerie`, `skeleton`, `dystopian`, `biomechanical`, `nightmare` |
| S1 | Nội Thất & Tĩnh Vật Ánh Sáng Cửa Sổ (Johannes Vermeer & Chardin) | `trong phòng`, `nội thất`, `tĩnh vật`, `cửa sổ`, `đọc sách`, `tách trà`, `bàn làm việc`, `ấm cúng`, `tĩnh lặng`, `bình yên`, `hoa trên bàn`, `phòng khách`, `quán cà phê`, `room`, `interior`, `still life`, `window light`, `cozy`, `quiet`, `tea`, `vermeer`, `reading` |
| A1 | Trừu Tượng & Biển Giông Thăng Hoa (J.M.W. Turner & Kandinsky) | `bão biển`, `sóng thần`, `biển động`, `giông bão`, `trừu tượng`, `xoáy màu`, `mơ màng`, `cuồng nộ`, `sóng vỗ`, `bão tuyết`, `tempest`, `stormy sea`, `tidal wave`, `storm`, `swirling colors`, `turner`, `sublime`, `abstract`, `ocean gale` |
| P1 | Chân Dung Điện Ảnh & Biểu Cảm (Steve McCurry & Helmut Newton) | `chân dung`, `khuôn mặt`, `gương mặt`, `cô gái`, `chàng trai`, `người đẹp`, `nữ sinh`, `doanh nhân`, `nụ cười`, `mỹ nhân`, `nữ hiệp`, `thần thái`, `portrait`, `girl`, `girls`, `woman`, `women`, `man`, `face`, `model`, `expressive gaze` |
| Cine-Master | Điện Ảnh Hollywood Bom Tấn (Blockbuster) | (mặc định khi không nhánh nào khớp) |

## 30 prompt mẫu (Kho nhân vật giả định: Tiểu Vũ/TV01, Lão Trần/LT02; mọi lớp bật; Seedance 2.5, 15 giây, 16:9)

### 01. [T1] Đối Thoại & Trò Chuyện (Over-the-shoulder, 85mm, ánh sáng mềm)

- Gốc: `Tiểu Vũ và Lão Trần ngồi đối thoại bên bếp lửa, ông hỏi về chuyến đi, cô trả lời khẽ`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: character, style, shot, angle, lens, lighting, palette · Nhân vật: Tiểu Vũ, Lão Trần
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Tiểu Vũ và Lão Trần ngồi đối thoại bên bếp lửa, ông hỏi về chuyến đi, cô trả lời khẽ. Nhân vật: Tiểu Vũ: cô gái 20 tuổi, tóc đen dài ngang lưng, áo dài trắng, ánh mắt kiên định; Lão Trần: ông lão 70 tuổi râu bạc, áo nâu sờn, chống gậy trúc. Hình ảnh: visual style T1 Đối thoại điện ảnh (natural conversational rhythm, expressive faces, calm steady camera); Medium Shot (MS) over-the-shoulder two-shot, shot/reverse-shot coverage; Eye Level, 180-degree rule respected, subtle slow push-in; 85mm Portrait Lens f/2, shallow depth of field, natural focus pull between speakers; Soft key light with gentle wrap, warm practical fill, no harsh contrast; Warm neutral skin-tone palette, soft cinematic color grading; balanced two-person framing, clean breathing space, lip-sync friendly steady composition.

### 02. [T1] Đối Thoại & Trò Chuyện (Over-the-shoulder, 85mm, ánh sáng mềm)

- Gốc: `Hai người bạn trò chuyện trên ghế đá công viên lúc chiều tà`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Hai người bạn trò chuyện trên ghế đá công viên lúc chiều tà. Hình ảnh: visual style T1 Đối thoại điện ảnh (natural conversational rhythm, expressive faces, calm steady camera); Medium Shot (MS) over-the-shoulder two-shot, shot/reverse-shot coverage; Eye Level, 180-degree rule respected, subtle slow push-in; 85mm Portrait Lens f/2, shallow depth of field, natural focus pull between speakers; Soft key light with gentle wrap, warm practical fill, no harsh contrast; Warm neutral skin-tone palette, soft cinematic color grading; balanced two-person framing, clean breathing space, lip-sync friendly steady composition.

### 03. [T1] Đối Thoại & Trò Chuyện (Over-the-shoulder, 85mm, ánh sáng mềm)

- Gốc: `Cô giáo nói với học sinh trước cổng trường, học sinh cúi đầu nghe`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Cô giáo nói với học sinh trước cổng trường, học sinh cúi đầu nghe. Hình ảnh: visual style T1 Đối thoại điện ảnh (natural conversational rhythm, expressive faces, calm steady camera); Medium Shot (MS) over-the-shoulder two-shot, shot/reverse-shot coverage; Eye Level, 180-degree rule respected, subtle slow push-in; 85mm Portrait Lens f/2, shallow depth of field, natural focus pull between speakers; Soft key light with gentle wrap, warm practical fill, no harsh contrast; Warm neutral skin-tone palette, soft cinematic color grading; balanced two-person framing, clean breathing space, lip-sync friendly steady composition.

### 04. [P1-Macro] Chân Dung Chi Tiết Biểu Cảm (Micro Detail)

- Gốc: `Cận cảnh đôi mắt ngấn nước mắt của Tiểu Vũ`
- Lớp đã có sẵn (không chèn): shot · Lớp đã chèn: character, style, angle, lens, lighting, palette · Nhân vật: Tiểu Vũ
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Cận cảnh đôi mắt ngấn nước mắt của Tiểu Vũ. Nhân vật: Tiểu Vũ: cô gái 20 tuổi, tóc đen dài ngang lưng, áo dài trắng, ánh mắt kiên định. Hình ảnh: visual style P1 Chân dung chi tiết có chủ ý (Steve McCurry & Helmut Newton); Eye Level micro view; Macro Lens 100mm, razor sharp focus, paper-thin depth of field; Volumetric Lighting, intentional catchlight in iris, high textural clarity; cinematic high-contrast grading, deep black shadows; focused micro composition, clean negative breathing space, hyper-realistic skin & fabric pore textures.

### 05. [P1-Macro] Chân Dung Chi Tiết Biểu Cảm (Micro Detail)

- Gốc: `Chiếc nhẫn bạc xoay chậm trên bàn gỗ, chi tiết hoa văn`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Chiếc nhẫn bạc xoay chậm trên bàn gỗ, chi tiết hoa văn. Hình ảnh: visual style P1 Chân dung chi tiết có chủ ý (Steve McCurry & Helmut Newton); Extreme Close-Up (ECU); Eye Level micro view; Macro Lens 100mm, razor sharp focus, paper-thin depth of field; Volumetric Lighting, intentional catchlight in iris, high textural clarity; cinematic high-contrast grading, deep black shadows; focused micro composition, clean negative breathing space, hyper-realistic skin & fabric pore textures.

### 06. [F1] Fantasy Cổ Tích & Thiên Nhiên (Alan Lee & John Howe)

- Gốc: `Khu rừng cổ tích rêu phong, suối nhỏ chảy qua gốc cây cổ thụ`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Khu rừng cổ tích rêu phong, suối nhỏ chảy qua gốc cây cổ thụ. Hình ảnh: visual style F1 Fantasy thiên nhiên & cổ tích Alan Lee & John Howe (overgrown mossy roots, weathered stones, clean negative space); Full Shot (FS) 3-layer depth landscape; Eye Level with leading stone path into the depth; 24mm Wide Angle Lens, Deep Focus; Soft morning sunlight diffusing through atmospheric mist, volumetric god rays; antique organic palette of Moss Green, Earth Brown and Pale Cream; 3-layer depth composition, natural curved linework, gentle mist atmosphere.

### 07. [F1] Fantasy Cổ Tích & Thiên Nhiên (Alan Lee & John Howe)

- Gốc: `Lâu đài trên đỉnh núi trong sương sớm, đàn chim bay qua tháp`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Lâu đài trên đỉnh núi trong sương sớm, đàn chim bay qua tháp. Hình ảnh: visual style F1 Fantasy thiên nhiên & cổ tích Alan Lee & John Howe (overgrown mossy roots, weathered stones, clean negative space); Full Shot (FS) 3-layer depth landscape; Eye Level with leading stone path into the depth; 24mm Wide Angle Lens, Deep Focus; Soft morning sunlight diffusing through atmospheric mist, volumetric god rays; antique organic palette of Moss Green, Earth Brown and Pale Cream; 3-layer depth composition, natural curved linework, gentle mist atmosphere.

### 08. [F2] Fantasy Kịch Tính & Hắc Ám (Frank Frazetta & Aleksi Briclot)

- Gốc: `Chiến binh rượt đuổi quái vật qua cánh đồng dung nham`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Chiến binh rượt đuổi quái vật qua cánh đồng dung nham. Hình ảnh: visual style F2 Fantasy kịch tính Frank Frazetta & Aleksi Briclot (bold heroic silhouette, muscular tension, rough rock and molten metal textures); Cowboy Shot (CS) action pose; Low Angle, dramatic heroic view, Dutch tilt; 24mm High Dynamic Motion Cine Lens; Fiery orange directional rim light cutting through smoke, deep black shadow contrast; Dramatic Crimson Red, Fire Amber and Deep Shadow Black palette; diagonal dynamic composition, sharp aggressive silhouettes, heavy textural grime.

### 09. [F2] Fantasy Kịch Tính & Hắc Ám (Frank Frazetta & Aleksi Briclot)

- Gốc: `Sát thủ vung đao trong hẻm tối, lửa cháy phía sau`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Sát thủ vung đao trong hẻm tối, lửa cháy phía sau. Hình ảnh: visual style F2 Fantasy kịch tính Frank Frazetta & Aleksi Briclot (bold heroic silhouette, muscular tension, rough rock and molten metal textures); Cowboy Shot (CS) action pose; Low Angle, dramatic heroic view, Dutch tilt; 24mm High Dynamic Motion Cine Lens; Fiery orange directional rim light cutting through smoke, deep black shadow contrast; Dramatic Crimson Red, Fire Amber and Deep Shadow Black palette; diagonal dynamic composition, sharp aggressive silhouettes, heavy textural grime.

### 10. [C1] Không Gian Lớn & Ánh Màu (Alena Aenami & John Harris)

- Gốc: `Phi thuyền cô độc trôi giữa ngân hà, bầu trời hoàng hôn tím`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Phi thuyền cô độc trôi giữa ngân hà, bầu trời hoàng hôn tím. Hình ảnh: visual style C1 Không gian lớn & Ánh màu Alena Aenami & John Harris (tiny human scale vs colossal cosmic architecture, wide negative space); Extreme Wide Establishing Shot (EWS); Wide Horizon panoramic view; 16mm Ultra-Wide Angle Lens, infinite depth of field; Luminous starlight, cosmic twilight glow, atmospheric scattering; Sunset Golden Hour and Violet Twilight cosmic palette, warm and cool atmospheric contrast; monumental scale balance, ultra-wide negative space, glowing volumetric celestial light.

### 11. [C1] Không Gian Lớn & Ánh Màu (Alena Aenami & John Harris)

- Gốc: `Người đứng một mình trước chân trời mênh mông sau cơn mưa`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Người đứng một mình trước chân trời mênh mông sau cơn mưa. Hình ảnh: visual style C1 Không gian lớn & Ánh màu Alena Aenami & John Harris (tiny human scale vs colossal cosmic architecture, wide negative space); Extreme Wide Establishing Shot (EWS); Wide Horizon panoramic view; 16mm Ultra-Wide Angle Lens, infinite depth of field; Luminous starlight, cosmic twilight glow, atmospheric scattering; Sunset Golden Hour and Violet Twilight cosmic palette, warm and cool atmospheric contrast; monumental scale balance, ultra-wide negative space, glowing volumetric celestial light.

### 12. [C2] Khoa Học Viễn Tưởng Mô-đun & Cơ Khí (Syd Mead & Chris Foss)

- Gốc: `Thành phố sci-fi neon về đêm, người máy khổng lồ bước qua đại lộ`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Thành phố sci-fi neon về đêm, người máy khổng lồ bước qua đại lộ. Hình ảnh: visual style C2 Sci-Fi mô-đun Syd Mead & Chris Foss (modular panel seams, weathered chrome, painted metal functionalism); Medium Wide Shot (MWS); Low Angle high-tech perspective; Anamorphic Lens, elliptical horizontal flares, razor sharp geometry; Industrial spotlights, hazard light strobes, tungsten blue key light, neon wet puddle reflections; Teal and Orange neon cyber palette, cold cyan key and warm tungsten accents; hard-surface geometric lines, layered metallic seams, high-contrast industrial lighting.

### 13. [C2] Khoa Học Viễn Tưởng Mô-đun & Cơ Khí (Syd Mead & Chris Foss)

- Gốc: `Xưởng cơ khí tương lai, cánh tay robot lắp ráp mô-đun`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Xưởng cơ khí tương lai, cánh tay robot lắp ráp mô-đun. Hình ảnh: visual style C2 Sci-Fi mô-đun Syd Mead & Chris Foss (modular panel seams, weathered chrome, painted metal functionalism); Medium Wide Shot (MWS); Low Angle high-tech perspective; Anamorphic Lens, elliptical horizontal flares, razor sharp geometry; Industrial spotlights, hazard light strobes, tungsten blue key light, neon wet puddle reflections; Teal and Orange neon cyber palette, cold cyan key and warm tungsten accents; hard-surface geometric lines, layered metallic seams, high-contrast industrial lighting.

### 14. [E1] Bi Kịch & Lịch Sử Hùng Tráng (Ilya Repin & Gustave Doré)

- Gốc: `Nhà vua đau khổ trước triều đình sau tin bại trận`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Nhà vua đau khổ trước triều đình sau tin bại trận. Hình ảnh: visual style E1 Bi kịch & Lịch sử Ilya Repin & Gustave Doré (intense emotional climax, rich heavy fabric textures, majestic crowd dynamics); Medium Full Shot (MFS) tableau composition; Slightly low dramatic theatrical stage perspective; 35mm Cine Lens, high optical resolution; Baroque dramatic chiaroscuro lighting, warm golden candle highlights, deep expressive shadows; Rich Umber, Royal Burgundy Crimson and Warm Candle Gold antique palette; theatrical dynamic composition, dense expressive gestures, layered historical costumes.

### 15. [E1] Bi Kịch & Lịch Sử Hùng Tráng (Ilya Repin & Gustave Doré)

- Gốc: `Đoàn quân đội trở về thánh đường trong tang thương`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Đoàn quân đội trở về thánh đường trong tang thương. Hình ảnh: visual style E1 Bi kịch & Lịch sử Ilya Repin & Gustave Doré (intense emotional climax, rich heavy fabric textures, majestic crowd dynamics); Medium Full Shot (MFS) tableau composition; Slightly low dramatic theatrical stage perspective; 35mm Cine Lens, high optical resolution; Baroque dramatic chiaroscuro lighting, warm golden candle highlights, deep expressive shadows; Rich Umber, Royal Burgundy Crimson and Warm Candle Gold antique palette; theatrical dynamic composition, dense expressive gestures, layered historical costumes.

### 16. [C1] Không Gian Lớn & Ánh Màu (Alena Aenami & John Harris)

- Gốc: `Cao bồi cưỡi ngựa băng qua sa mạc cát bụi lúc hoàng hôn`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Cao bồi cưỡi ngựa băng qua sa mạc cát bụi lúc hoàng hôn. Hình ảnh: visual style C1 Không gian lớn & Ánh màu Alena Aenami & John Harris (tiny human scale vs colossal cosmic architecture, wide negative space); Extreme Wide Establishing Shot (EWS); Wide Horizon panoramic view; 16mm Ultra-Wide Angle Lens, infinite depth of field; Luminous starlight, cosmic twilight glow, atmospheric scattering; Sunset Golden Hour and Violet Twilight cosmic palette, warm and cool atmospheric contrast; monumental scale balance, ultra-wide negative space, glowing volumetric celestial light.

### 17. [W1] Miền Tây & Phiêu Lưu Thám Hiểm (Frederic Remington & Frank Schoonover)

- Gốc: `Nhóm thám hiểm vượt hẻm núi đỏ, bụi mù phía sau`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Nhóm thám hiểm vượt hẻm núi đỏ, bụi mù phía sau. Hình ảnh: visual style W1 Miền Tây & Phiêu lưu thám hiểm Frederic Remington & Frank Schoonover (sunburnt dust trails, worn leather, rugged sandstone canyons); Cowboy Shot (CS) tracking across vista; Eye Level tracking view across rugged landscape; 50mm Prime Lens with raking dust haze; Harsh blazing desert sunlight casting long raking shadows, golden sand bounce fill; Sunburnt Ochre, Terracotta Earth and Faded Turquoise sky palette; expansive horizontal horizon, granular atmospheric dust texture, dynamic motion trails.

### 18. [G1] Đồ Họa Đường Nét & Mảng Phẳng (Moebius & Kilian Eng)

- Gốc: `Phong cách anime, cô gái tóc xanh đứng trên mái nhà`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Phong cách anime, cô gái tóc xanh đứng trên mái nhà. Hình ảnh: visual style G1 Đồ họa đường nét mảng phẳng Moebius (Jean Giraud) & Kilian Eng (intricate precise ink linework, bold graphic silhouette, flat aesthetic planes); Medium Shot (MS); Cinematic Geometric Eye Level; 50mm Prime Lens, razor sharp line definition; Clean graphic lighting, soft ambient fill, crisp rim line highlights; Harmonic limited graphic palette of Mustard Yellow, Mint Green and Coral Pink; clean contour linework, zero visual clutter, elegant flat colored negative space.

### 19. [G1] Đồ Họa Đường Nét & Mảng Phẳng (Moebius & Kilian Eng)

- Gốc: `Minh họa truyện tranh vẽ nét, thành phố mảng phẳng`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Minh họa truyện tranh vẽ nét, thành phố mảng phẳng. Hình ảnh: visual style G1 Đồ họa đường nét mảng phẳng Moebius (Jean Giraud) & Kilian Eng (intricate precise ink linework, bold graphic silhouette, flat aesthetic planes); Medium Shot (MS); Cinematic Geometric Eye Level; 50mm Prime Lens, razor sharp line definition; Clean graphic lighting, soft ambient fill, crisp rim line highlights; Harmonic limited graphic palette of Mustard Yellow, Mint Green and Coral Pink; clean contour linework, zero visual clutter, elegant flat colored negative space.

### 20. [D1] Gothic U Tối & Sinh Cơ Khí (H.R. Giger & Zdzisław Beksiński)

- Gốc: `Hành lang gothic ma quái với xương sống sinh học trên tường`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Hành lang gothic ma quái với xương sống sinh học trên tường. Hình ảnh: visual style D1 Biomechanical Gothic H.R. Giger & Zdzisław Beksiński (ribbed spine structures, organic tubes, ominous desolate architecture); Medium Close-Up (MCU); Slightly low claustrophobic unsettling angle; 35mm Cine Lens, high contrast; Icy cold rim light, narrow sliver of light cutting through heavy impenetrable darkness; Monochromatic Deep Charcoal Black, Bone White with subtle sickly viridian sheen; claustrophobic repeating bone textures, deep void negative space, cold organic-metallic fusion.

### 21. [D1] Gothic U Tối & Sinh Cơ Khí (H.R. Giger & Zdzisław Beksiński)

- Gốc: `Ác mộng dưới địa ngục, bóng người quái dị bước ra`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Ác mộng dưới địa ngục, bóng người quái dị bước ra. Hình ảnh: visual style D1 Biomechanical Gothic H.R. Giger & Zdzisław Beksiński (ribbed spine structures, organic tubes, ominous desolate architecture); Medium Close-Up (MCU); Slightly low claustrophobic unsettling angle; 35mm Cine Lens, high contrast; Icy cold rim light, narrow sliver of light cutting through heavy impenetrable darkness; Monochromatic Deep Charcoal Black, Bone White with subtle sickly viridian sheen; claustrophobic repeating bone textures, deep void negative space, cold organic-metallic fusion.

### 22. [S1] Nội Thất & Tĩnh Vật Ánh Sáng Cửa Sổ (Johannes Vermeer & Chardin)

- Gốc: `Trong phòng ấm cúng, ánh nắng cửa sổ chiếu lên tách trà và quyển sách`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Trong phòng ấm cúng, ánh nắng cửa sổ chiếu lên tách trà và quyển sách. Hình ảnh: visual style S1 Nội thất & Tĩnh vật Johannes Vermeer & Jean-Baptiste Chardin (poetic stillness, tactile linen, glazed ceramic and aged wood); Medium Shot (MS) intimate interior; Eye Level contemplative natural framing; 50mm Prime Lens (Nifty Fifty), gentle organic falloff; Soft north window side light (Vermeer natural light), gentle delicate wall bounce falloff; Harmonic palette of Ultramarine Blue, Warm Ochre Yellow, Pearl White and Aged Timber Brown; golden ratio interior framing, soft tactile textures, spacious peaceful negative space.

### 23. [S1] Nội Thất & Tĩnh Vật Ánh Sáng Cửa Sổ (Johannes Vermeer & Chardin)

- Gốc: `Quán cà phê tĩnh lặng buổi sáng, hơi nước bốc lên`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Quán cà phê tĩnh lặng buổi sáng, hơi nước bốc lên. Hình ảnh: visual style S1 Nội thất & Tĩnh vật Johannes Vermeer & Jean-Baptiste Chardin (poetic stillness, tactile linen, glazed ceramic and aged wood); Medium Shot (MS) intimate interior; Eye Level contemplative natural framing; 50mm Prime Lens (Nifty Fifty), gentle organic falloff; Soft north window side light (Vermeer natural light), gentle delicate wall bounce falloff; Harmonic palette of Ultramarine Blue, Warm Ochre Yellow, Pearl White and Aged Timber Brown; golden ratio interior framing, soft tactile textures, spacious peaceful negative space.

### 24. [A1] Trừu Tượng & Biển Giông Thăng Hoa (J.M.W. Turner & Kandinsky)

- Gốc: `Bão biển cuồng nộ, sóng thần vỗ vào vách đá`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Bão biển cuồng nộ, sóng thần vỗ vào vách đá. Hình ảnh: visual style A1 Trừu tượng & Biểu hiện cảm xúc J.M.W. Turner (elemental vortex, dissolving sky-sea boundaries, sublime force); Wide Atmospheric Vista (WAV); Dynamic sweeping angle caught in the tempest; 24mm Cine Lens with water droplet reflections; Atmospheric swirling light breaking through storm clouds, radiant elemental glow; Storm Sulfur Yellow, Deep Ocean Prussian Blue and Whipped Seafoam White palette; vortical spiral composition, dissolved boundaries, fluid atmospheric motion textures.

### 25. [A1] Trừu Tượng & Biển Giông Thăng Hoa (J.M.W. Turner & Kandinsky)

- Gốc: `Xoáy màu trừu tượng mơ màng chuyển động chậm`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Xoáy màu trừu tượng mơ màng chuyển động chậm. Hình ảnh: visual style A1 Trừu tượng & Biểu hiện cảm xúc J.M.W. Turner (elemental vortex, dissolving sky-sea boundaries, sublime force); Wide Atmospheric Vista (WAV); Dynamic sweeping angle caught in the tempest; 24mm Cine Lens with water droplet reflections; Atmospheric swirling light breaking through storm clouds, radiant elemental glow; Storm Sulfur Yellow, Deep Ocean Prussian Blue and Whipped Seafoam White palette; vortical spiral composition, dissolved boundaries, fluid atmospheric motion textures.

### 26. [P1] Chân Dung Điện Ảnh & Biểu Cảm (Steve McCurry & Helmut Newton)

- Gốc: `Chân dung cô gái mỉm cười dưới mưa, thần thái tự tin`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Chân dung cô gái mỉm cười dưới mưa, thần thái tự tin. Hình ảnh: visual style P1 Chân dung điện ảnh Steve McCurry & Helmut Newton (expressive emotive gaze, natural breathing space); Close-Up (CU) portrait; Slightly low eye-level cinematic framing; 85mm Portrait Lens f/1.4, creamy optical bokeh; Rembrandt Lighting with chiaroscuro triangle on cheek, catchlight in eyes, subsurface scattering on skin, warm rim light; Teal and Orange cinema color palette, Blue Key Light, Warm Amber Fill Light; rule of thirds composition, rich skin subsurface texture, controlled shadow gradient.

### 27. [P1] Chân Dung Điện Ảnh & Biểu Cảm (Steve McCurry & Helmut Newton)

- Gốc: `Doanh nhân đứng trước cửa kính tòa nhà, nụ cười nhẹ`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Doanh nhân đứng trước cửa kính tòa nhà, nụ cười nhẹ. Hình ảnh: visual style P1 Chân dung điện ảnh Steve McCurry & Helmut Newton (expressive emotive gaze, natural breathing space); Close-Up (CU) portrait; Slightly low eye-level cinematic framing; 85mm Portrait Lens f/1.4, creamy optical bokeh; Rembrandt Lighting with chiaroscuro triangle on cheek, catchlight in eyes, subsurface scattering on skin, warm rim light; Teal and Orange cinema color palette, Blue Key Light, Warm Amber Fill Light; rule of thirds composition, rich skin subsurface texture, controlled shadow gradient.

### 28. [Cine-Master] Điện Ảnh Hollywood Bom Tấn (Blockbuster)

- Gốc: `Chiếc xe chạy qua cầu lúc nửa đêm, camera bám theo`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: style, shot, angle, lens, lighting, palette
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Chiếc xe chạy qua cầu lúc nửa đêm, camera bám theo. Hình ảnh: chuẩn điện ảnh Hollywood Masterpiece (balanced 3-layer composition, controlled negative breathing space); Medium Shot (MS); Cinematic Eye Level framing; 50mm Prime Lens (Nifty Fifty); Three-point lighting, Blue Key Light, Warm Orange Fill Light, subtle catchlight; Cinematic Color Grading, 35mm Tungsten Film Stock, subtle natural film grain; blockbuster cinematic framing, balanced rule-of-thirds, rich tactile textures.

### 29. [C1] Không Gian Lớn & Ánh Màu (Alena Aenami & John Harris)

- Gốc: `Tiểu Vũ chạy xe máy qua phố cổ, ống kính 85mm, ánh sáng hoàng hôn`
- Lớp đã có sẵn (không chèn): lens, lighting · Lớp đã chèn: character, style, shot, angle, palette · Nhân vật: Tiểu Vũ
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Tiểu Vũ chạy xe máy qua phố cổ, ống kính 85mm, ánh sáng hoàng hôn. Nhân vật: Tiểu Vũ: cô gái 20 tuổi, tóc đen dài ngang lưng, áo dài trắng, ánh mắt kiên định. Hình ảnh: visual style C1 Không gian lớn & Ánh màu Alena Aenami & John Harris (tiny human scale vs colossal cosmic architecture, wide negative space); Extreme Wide Establishing Shot (EWS); Wide Horizon panoramic view; Sunset Golden Hour and Violet Twilight cosmic palette, warm and cool atmospheric contrast; monumental scale balance, ultra-wide negative space, glowing volumetric celestial light.

### 30. [Cine-Master] Điện Ảnh Hollywood Bom Tấn (Blockbuster)

- Gốc: `02. Lão Trần chống gậy đi qua cánh đồng lúa chín`
- Lớp đã có sẵn (không chèn): không · Lớp đã chèn: character, style, shot, angle, lens, lighting, palette · Nhân vật: Lão Trần
- Kết quả gửi Dola: Tạo video Seedance 2.5 dài 15 giây, tỷ lệ khung hình 16:9 (ngang). Không hỏi lại, tạo video ngay. Lão Trần chống gậy đi qua cánh đồng lúa chín. Nhân vật: Lão Trần: ông lão 70 tuổi râu bạc, áo nâu sờn, chống gậy trúc. Hình ảnh: chuẩn điện ảnh Hollywood Masterpiece (balanced 3-layer composition, controlled negative breathing space); Medium Shot (MS); Cinematic Eye Level framing; 50mm Prime Lens (Nifty Fifty); Three-point lighting, Blue Key Light, Warm Orange Fill Light, subtle catchlight; Cinematic Color Grading, 35mm Tungsten Film Stock, subtle natural film grain; blockbuster cinematic framing, balanced rule-of-thirds, rich tactile textures.
