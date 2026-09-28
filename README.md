# Animal TV Generator

Tool tạo video dài kiểu "Cat TV / Pet TV" (1h, 4h, 8h...): một nền cố định, con vật chạy qua chạy lại ngẫu nhiên và thỉnh thoảng kêu. Mọi thứ ghép bằng code và encode bằng FFmpeg, nên chỉ cần vài clip ngắn của con vật (tạo bằng Veo) là ra được video nhiều giờ không lặp lại.

## Chạy tool

1. Nhấp đúp **`run.bat`**.
   - Lần đầu tool tự cài thư viện Python và FFmpeg (qua winget) nếu máy chưa có.
   - Trình duyệt tự mở **http://localhost:8765**.
2. Cửa sổ đen phải để mở trong lúc dùng tool. Đóng cửa sổ đó là tắt tool.

Yêu cầu: Windows 10/11, Python 3.10 trở lên.

## Cách dùng (theo thứ tự trên giao diện)

### 1. Background
Kéo thả ảnh nền (PNG/JPG, nên là 16:9, ví dụ tường gỗ có lỗ chuột). Chưa có nền thì tool dùng tạm nền gỗ.

Trên ảnh bên phải có **khung vàng**: đó là vùng *chân* con vật được đi.
- Kéo bên trong khung để di chuyển.
- Kéo góc để đổi kích thước.
- Kéo ra ngoài khung để vẽ khung mới.

Nên đặt khung trùng với mặt sàn.

### 2. Con vật
Bấm **+ Thêm con vật** rồi chọn loài (chuột, hamster, mèo, chó, chim, côn trùng, cá hoặc Khác…). Tool đặt sẵn kích thước và kiểu chạy hợp với loài đó.

Mỗi con vật là một thẻ, phần đầu thẻ gồm:
- ảnh nhỏ;
- tên (bấm để sửa);
- công tắc bật/tắt con vật trong video;
- **− N con +**: số con cùng lúc trên màn hình;
- ▾ thu gọn;
- ✕ xóa.

Phần dưới thẻ có 4 tab.

**🎞 Clip**: 3 ô *Đứng yên / Đi / Chạy*.

| Ô | Dùng khi | Gợi ý prompt Veo (xem `mouse_asset_prompts.md`) |
|---|---|---|
| **Đứng yên** (idle) | đứng yên, quay đầu | clip A (idle), D (grooming) |
| **Đi** (walk) | đi chậm | clip B (walk cycle tại chỗ) |
| **Chạy** (run) | chạy vụt | clip C (run cycle tại chỗ) |

- Kéo 1 clip vào đúng ô, hoặc **kéo nhiều clip cùng lúc** vào tab. Tên file có chữ `idle` / `walk` / `run` (hoặc `dung`, `di`, `chay`) sẽ tự vào đúng ô.
- Chỉ cần ít nhất **1 clip**. Clip nào thiếu thì tool dùng clip khác thay.
- Nhận các định dạng: MP4/MOV nền xanh (Veo), WebM có alpha, PNG, hoặc ZIP chứa chuỗi PNG.
- Khi upload, tool tự làm các bước:
  - dò màu nền xanh;
  - xóa nền, bóng và sàn;
  - khử viền xanh;
  - cắt sát con vật;
  - nếu con vật trôi ngang trong clip thì kéo nó về giữa.
- Ô clip chạy animation đã tách nền trên nền caro.
- Bấm vào một ô để chỉnh riêng clip đó:
  - **Cắt từ / đến** (giây). Veo hay có vài frame đầu bị lỗi.
  - **Tự tìm đoạn lặp mượt**.
  - **Chạy tới rồi lui**: dùng khi chỗ lặp bị giật.
  - To / nhỏ riêng clip.
  - Thay hoặc xóa clip.

**🏃 Chuyển động**:
- **Mẫu có sẵn**: đặt nhanh kiểu chạy theo loài.
- **Kích thước**: % chiều ngang khung hình.
- **Clip gốc nhìn về**: hướng con vật trong clip gốc. Nếu thấy con vật đi giật lùi thì bấm đổi.
- 3 thanh đơn giản:
  - **Tốc độ**: chậm ↔ nhanh.
  - **Hiếu động**: hay nằm ↔ chạy suốt.
  - **Nhút nhát**: ở lại ↔ hay trốn khỏi màn.
- **Nâng cao**: số chính xác (px/giây trên khung 1920 px, thời gian dừng, tần suất từng hành vi).

**🟩 Tách nền**:

| Thanh | Tác dụng |
|---|---|
| Xóa nền xanh | tăng khi còn sót nền xanh; giảm khi bị ăn vào con vật |
| Viền mềm | độ mềm của viền |
| Xóa bóng / sàn | tăng khi còn bóng đổ hoặc mặt sàn xanh đậm dưới chân (clip Veo hay bị) |
| Khử ánh xanh | giảm ánh xanh hắt lên lông |

- Ảnh xem thử cập nhật ngay khi kéo thanh.
- Clip đã nhập **không tự đổi** khi kéo thanh. Tab hiện chấm vàng kèm nút **Áp dụng cho N clip**; bấm nút này để tách nền lại.

**🔊 Tiếng kêu**: kéo thả một hoặc nhiều file. Tool phát ngẫu nhiên theo khoảng "Cách nhau" và "Âm lượng".

**Xem trực tiếp**: ảnh nền bên phải chạy thử các con vật theo đúng chuyển động của video thật (cùng engine), và cập nhật ngay khi chỉnh.
- Bấm vào một con trên ảnh để nhảy tới thẻ của nó.
- **🎲 Cảnh khác**: xem một kịch bản ngẫu nhiên khác.
- **🔊 Nghe tiếng**: phát cả tiếng kêu.

### 3. Âm nền
Một file âm nền (tiếng phòng, gió...) được lặp suốt video, có chỉnh âm lượng.

### 4. Render
- **Thời lượng**: chọn 30 phút đến 10 giờ, hoặc tự gõ `hh:mm:ss`.
- **Độ phân giải**: 720p / 1080p / 1440p / 4K. **FPS**: 24 / 25 / 30 / 60.
- **Seed**:
  - Để trống thì mỗi lần ra một video khác.
  - Nhập số thì lần nào cũng ra đúng video đó.
  - Nút 🎲 tạo seed mới.
- **Bóng đổ**: bóng mờ dưới chân. **To hơn khi ở gần**: con vật ở phía dưới khung to hơn một chút.
- **CRF**: chất lượng. 18–22 là hợp lý; số càng nhỏ càng nét và file càng nặng.

### Nút bấm
- **▶ Preview 60s**: render nhanh 60 giây ở 720p (khoảng 15 giây) rồi phát ngay trên trang. Nên xem preview trước khi render dài.
- **⬇ Tạo video**: render đầy đủ theo cài đặt.
- **Tạo N video**: xếp hàng N video, mỗi video một seed khác nhau.
- Mục **Công việc** hiện tiến độ, tốc độ (fps) và thời gian còn lại, có nút Hủy.

## Kết quả

Nằm trong `D:\AnimalTV\output\`:

```
CatTV_mouse_20260928_001.mp4            video
CatTV_mouse_20260928_001.jpg            thumbnail (khung có nhiều con vật nhất)
CatTV_mouse_20260928_001.json           seed, cấu hình, thời gian render
CatTV_mouse_20260928_001.timeline.json  toàn bộ đường đi và tiếng kêu (để debug)
```

## Tốc độ (máy hiện tại: 16 luồng CPU, encode libx264)

| Video | Thời gian render ước tính |
|---|---|
| Preview 60s 720p | khoảng 13 giây |
| 1 giờ 1080p30 | khoảng 12 phút |
| 8 giờ 1080p30 | khoảng 1,5 giờ |
| 8 giờ 4K30 | khoảng 6 giờ |

Video được chia thành các đoạn 5 phút và render song song.

**Render tiếp khi bị gián đoạn**: chỉ áp dụng khi đã **đặt seed cố định**. Nếu video dài bị hủy hoặc máy tắt giữa chừng, bấm Tạo video lại với đúng cài đặt cũ, tool sẽ bỏ qua các đoạn đã render xong. Các đoạn tạm nằm ở `output\.work\`. Xóa thư mục này được khi không render.

## Mẹo tạo clip bằng Veo cho đẹp
- Con vật nhỏ trong khung (khoảng 1/3 chiều ngang), thấy đủ đuôi, không chạm mép.
- Nền xanh phẳng: không sàn, không bóng, không gradient.
- Walk/run nên **đi tại chỗ** (camera bám theo). Nếu con vật trôi ngang thì tool vẫn tự kéo về giữa, nhưng đi tại chỗ vẫn đẹp hơn.
- Mỗi clip 4–8 giây là đủ.

## Chưa có trong bản này (v2)
- Mask che khuất: con vật đi sau đồ vật.
- Vùng đi dạng đa giác, tránh vật cản và tìm đường.
- Clip sự kiện: chuột ló ra hoặc chui vào lỗ.
- Góc nhìn từ trên xuống có xoay theo hướng đi.
- Playlist nhiều cảnh.

## Cấu trúc code
```
app/main.py         web server + API (FastAPI)
app/timeline.py     sinh hành vi ngẫu nhiên theo seed
app/sampler.py      thời điểm t -> vị trí, hướng, frame của từng con
app/compositor.py   ghép frame (nền + bóng + sprite)
app/audio_mix.py    trộn âm nền + tiếng kêu
app/render.py       render song song theo đoạn, ghép file, thumbnail, metadata
app/chroma.py       tách nền xanh
app/assets.py       nhập ảnh, clip, âm thanh
web/                giao diện
tests/              pytest
```
