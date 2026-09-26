# Prompt cho routine Claude — "Lời khuyên SOXL theo phương pháp Máy in tiền"

Chạy 2–3 lần/ngày giao dịch Mỹ: **08:45 ET** (pre-market), **10:15 ET** và **14:30 ET** (in-market). Repo: `soxl-briefing`.

## Bước làm

1. Chạy script tín hiệu (không sửa `soxl_levels.py`, `ta_levels.py`):
   ```
   .venv/Scripts/python soxl_method.py --capital <VỐN> --md --save reports/method --pdf
   ```
   Thay `<VỐN>` bằng tổng vốn giao dịch của tôi (CAD cho SOXL.NE; nếu chưa biết thì bỏ `--capital`).
2. Đọc `knowledge/soxl-may-in-tien-tong-hop.md` (bắt buộc). Khi cần chi tiết, đọc thêm `knowledge/soxl-may-in-tien-kien-thuc.md`.
3. Nếu là pre-market, tìm nhanh tin ảnh hưởng semis hôm nay (earnings NVDA/AMD/MU/TSM, CPI/FOMC, tin Mỹ–Trung/thuế). Không quá 3 dòng.
4. Viết bản khuyến nghị (tiếng Việt) theo mẫu dưới, lưu `reports/method/advice-YYYY-MM-DD-HHMM.md` và trả về nội dung.
5. Xuất PDF cho bản khuyến nghị (và bản briefing ngày nếu có):
   ```
   .venv/Scripts/python md_to_pdf.py reports/method/advice-YYYY-MM-DD-HHMM.md --title "SOXL khuyến nghị DD/MM/YYYY HH:MM ET"
   .venv/Scripts/python md_to_pdf.py reports/YYYY-MM-DD.md
   ```
   Nêu đường dẫn PDF ở cuối câu trả lời.

## Mẫu đầu ra

```
# SOXL — <ngày giờ ET> (<pre-market | in-market | after-close>)

## 1. Trạng thái (từ soxl_method.py)
- SOXL (US): đóng cửa / hôm nay / regime / SMA50-200 / ±2σ và ±3σ / MACD đỏ (hướng) + vị trí so với zero line của cả đường xanh và đỏ
- Giá so với SMA200: nếu đang dưới 200 ngày → nhắc luật "gap up để đóng trên 200 ngày rồi đi thêm 15–20%"
- SOXL.NE (CAD): cùng các mục
- Gap sống gần nhất (up dưới, down trên)
- Bậc gap down hôm nay + cỡ lệnh 1/4 của 1/5

## 2. Theo phương pháp investor → NÊN LÀM GÌ LÚC NÀY
Chọn đúng MỘT hành động chính và nêu mức giá cụ thể trên SOXL.NE:
- KHÔNG LÀM GÌ (không gap down / mở cao đóng thấp / nu lô) — ngồi ngoài, giữ free share, đặt lệnh sẵn cho ngày mai.
- BỤP (đã có gap down chạm bậc) — bậc nào, bao nhiêu CAD/share, stop thủ vốn ở đâu (giá mua + offset), mốc ra +5%/nửa ba.
- GIỮ / BÒ LẾT (uptrend: MACD vượt zero — đường xanh trên zero là bắt đầu, cả hai đường trên zero là chắc — & đỏ đang lên, giá trên SMA50 & SMA200, mon men +2σ) — không bán, chỉ thủ vốn các lô mới; nêu mức +2σ/+3σ để theo dõi.
- AVERAGE UP (đủ cả 3: đã có free share + MACD lên + giá trên SMA50) — mua lô mới ở giá nào, stop thủ vốn ~1$ dưới giá mua (hoặc tại support test 3 lần), dời stop lô trước khi giá lên tiếp.
- ĐẨY (gap up ≥5%) — bán 1/3 tổng share tiền mới, stop cho phần còn lại. **Nếu MACD vượt zero đi lên**: chỉ đẩy khi giá mở cửa gap up vượt +3σ, mua lại khi quay về +2σ ("đẩy 3σ, mua lại 2σ").
- RA TIỀN MỚI (đóng dưới SMA50 không gap / dưới nửa ba đỏ).
- QUẢN LÝ LỆNH CŨ — **MACD xuống**: dời stop theo luật $10 / trailing (thủ lời). **MACD lên**: chỉ thủ vốn (stop tại giá mua + offset), không thủ lời; bị stop thì mua lại thấp hơn.
Kèm 2–4 gạch đầu dòng dẫn đúng luật của investor (tên luật: gap down 8/11/14/17, thủ vốn, xuống 10 lên 5, 1/3 gap up, free share, mon men −2σ, MACD đỏ...).

## 3. Đánh giá riêng của AI
- Đồng ý / không đồng ý với hành động ở mục 2 và vì sao (dữ liệu nào ủng hộ, dữ liệu nào phản bác).
- Rủi ro mà phương pháp investor không nói tới hôm nay (sự kiện vĩ mô, thanh khoản SOXL.NE, chênh FX CAD/USD, decay 3x, dữ liệu yfinance thiếu/trễ).
- Xác suất chủ quan cho 3 kịch bản đến hết phiên (tăng / giảm / sideway) và mức vô hiệu.
- Nếu tôi có vị thế đang mở (tôi sẽ nói trong tin nhắn trước), nêu stop cụ thể cho từng lô.

## 4. Việc cần làm trước lần chạy sau
- Lệnh chờ cần đặt (giá, số share), alert cần đặt (low hôm qua, SMA50, −2σ, gap gần nhất).
```

## Quy tắc viết
- Ngắn, số liệu trong bảng hoặc dòng riêng, không lặp lại JSON.
- Phân biệt rõ mức giá USD (SOXL) và CAD (SOXL.NE). Luật của investor tính trên SOXL US; hành động thực tế trên SOXL.NE.
- Không bao giờ khuyên average down/DCA, bắt đáy, mua after-hours, mua đuổi gap up, hay vào quá 1/5 vốn — trái phương pháp.
- Trong uptrend, không khuyên bán lô kẹt khi nó vừa về huề vốn ("chart lên cho huề vốn là đi luôn"); gỡ lô kẹt bằng bụp gap down → đẩy gap up với 1/5 thứ nhì.
- Nếu script lỗi/không có dữ liệu, nói rõ và chỉ đưa mục 3 dựa trên những gì có.
- Kết thúc bằng một câu: hành động chính + mức giá + điều kiện huỷ.
