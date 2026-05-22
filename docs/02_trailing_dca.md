# Chiến Lược Trailing DCA

## Nguồn Gốc

Chiến lược này lấy cảm hứng trực tiếp từ **3Commas** DCA Bot, bot giao dịch tự động phổ biến nhất cho crypto (hơn 500K người dùng). Khái niệm cốt lõi được điều chỉnh từ DCA chứng khoán truyền thống nhưng được nâng cấp với **safety orders** (mở rộng vị thế khi giảm) và **trailing take-profit** (chốt lời bằng cách đi theo momentum lên, sau đó bán khi pullback).

**Pionex** cung cấp một "DCA Bot" tương tự và **Bitsgap** có "DCA Bot" với chế độ "trailing". Ý tưởng đến từ **lý thuyết Martingale** -- gấp đôi xuống vị thế thua, nhưng với rủi ro có giới hạn thông qua giới hạn kích thước vị thế.

## Cách Hoạt Động

### Giai Đoạn 1: Lệnh Cơ Sở (Base Order)

Trên tick đầu tiên, bot đặt một **lệnh cơ sở** sử dụng 10% ngân sách ($200 trong $2,000). Điều này thiết lập vị thế ban đầu.

### Giai Đoạn 2: Safety Orders (Mở Rộng Vào)

Khi giá giảm từ điểm vào, bot đặt các lệnh mua ngày càng lớn hơn:

```
Safety Order #1: -3%  từ entry -> mua $200 * 1.5^0 = $200
Safety Order #2: -6%  từ entry -> mua $200 * 1.5^1 = $300
Safety Order #3: -12% từ entry -> mua $200 * 1.5^2 = $450
Safety Order #4: -20% từ entry -> mua $200 * 1.5^3 = $675
Safety Order #5: -30% từ entry -> mua $200 * 1.5^4 = $1,012
```

Mỗi safety order **lớn hơn 1.5 lần** so với cái trước. Việc mở rộng tích cực này nhanh chóng hạ giá vào trung bình, nên chỉ cần một cú bật nhỏ hơn là đạt được lợi nhuận.

**Ví dụ**: Nếu BTC vào ở $80,000 và giảm xuống $72,000 (-10%), safety orders #1-#3 kích hoạt. Giá trung bình có thể là ~$76,000. Một cú bật lên $77,520 (+2% từ trung bình) kích hoạt take-profit -- ngay cả khi giá vẫn thấp hơn 3% so với điểm vào.

### Giai Đoạn 3: Trailing Take-Profit

Khi lợi nhuận chưa thực hiện đạt **ngưỡng take-profit** (2% trên giá trung bình):

1. Chế độ trailing được kích hoạt, theo dõi đỉnh giá
2. Nếu giá tiếp tục tăng, đỉnh được cập nhật (chốt thêm lợi nhuận)
3. Nếu giá giảm **0.8% từ đỉnh**, bot bán 100% vị thế
4. Sau khi bán, toàn bộ chu kỳ reset và chờ điểm vào tiếp theo

```
avg_cost = $76,000
TP trigger = $77,520 (avg + 2%)
Giá chạm $78,000 -> đỉnh trailing = $78,000
Giá chạm $78,500 -> đỉnh trailing = $78,500
Giá giảm xuống $77,872 (0.8% dưới đỉnh) -> BÁN HẾT
Lợi nhuận: ~2.5% trên vị thế
```

### Giai Đoạn 4: Reset

Sau khi bán, bot reset hoàn toàn:
- Giá vào được xóa
- Tất cả cờ safety order reset
- Trạng thái trailing được xóa
- Sẵn sàng cho chu kỳ mới

## Tham Số

| Tham Số | Giá Trị | Mô Tả |
|-----------|-------|-------------|
| `base_order_pct` | 10% | % ngân sách cho lệnh mua ban đầu |
| `safety_deviations` | [3, 6, 12, 20, 30] | % giá giảm để kích hoạt mỗi safety order |
| `tp_pct` | 2.0% | Ngưỡng take-profit trên giá trung bình |
| `trailing_pct` | 0.8% | % giảm từ đỉnh để kích hoạt bán |
| `scale_factor` | 1.5x | Mỗi safety order lớn gấp 1.5 lần trước đó |

## Mô Hình Phí

Tất cả lệnh đều là **lệnh market** (phí taker 0.10% + slippage 0.02%). Chiến lược giao dịch ít -- trong thử nghiệm 7 ngày, chỉ thực hiện **1 giao dịch** (lệnh cơ sở), nghĩa là safety order không bao giờ kích hoạt vì giá không giảm đủ từ điểm vào.

## Điểm Mạnh

1. **Xuất sắc trong các đợt hồi phục chữ V**: Đây là điểm ngọt của chiến lược. Nếu giá giảm 10% rồi bật trở lại, safety order mua mạnh ở đáy, và trailing TP chốt lợi nhuận khi đi lên. Việc mở rộng tích cực (1.5x) có nghĩa là bạn mua NHIỀU HƠN với giá THẤP HƠN.

2. **Quản lý rủi ro tích hợp sẵn**: Kích thước vị thế có giới hạn. Tổng đầu tư tối đa qua tất cả safety order:
   ```
   $200 + $200 + $300 + $450 + $675 + $1,012 = $2,837
   Nhưng ngân sách chỉ có $2,000, nên các lệnh sau sẽ bị giới hạn.
   ```

3. **Trailing TP bắt được momentum**: Thay vì bán ở mục tiêu cố định (có thể bán ngay trước một đợt tăng 5%), trailing TP đi theo sóng lên và chỉ thoát khi có đảo chiều xác nhận.

4. **Tần suất giao dịch thấp = phí thấp**: Trong thử nghiệm đấu trường, tổng chi phí chỉ $0.24. Đây là chiến lược chủ động rẻ nhất.

5. **Tính trung bình tự động**: Tính toán giá trung bình đảm bảo bạn luôn biết chính xác cần bao nhiêu lợi nhuận để hòa vốn + TP.

6. **Reset hoàn toàn sau lợi nhuận**: Mỗi chu kỳ độc lập. Hiệu suất trong quá khứ không ảnh hưởng đến quyết định tương lai.

## Điểm Yếu

1. **Đóng băng trong các đợt giảm chậm**: Nếu giá giảm chậm (1% mỗi ngày trong 30 ngày), safety order kích hoạt từng cái một, hạ trung bình vào một vị thế thua lỗ. Giá không bao giờ bật đủ để kích hoạt TP, và bạn bị mắc kẹt trong vị thế dưới nước vô thời hạn.

2. **Bất động trong thị trường nhẹ nhàng**: Trong thử nghiệm đấu trường, giá chỉ chuyển động -2.7% từ điểm vào trong 7 ngày. Chỉ có lệnh cơ sở kích hoạt, và TP không bao giờ chạm. Chiến lược về cơ bản đứng yên -- $200 đầu tư, $1,800 ngồi không. ROI: -0.28%.

3. **Chỉ một chiều (long)**: Không có logic bên short. Trong thị trường gấu xác nhận, bot cứ mua các đợt dip mà tiếp tục dip.

4. **Rủi ro Martingale**: Mở rộng 1.5x có nghĩa là safety order muộn rất lớn. Nếu cả 5 đều kích hoạt, bạn đã triển khai toàn bộ ngân sách vào thời điểm sợ hãi tối đa. Nếu giá giảm thêm, bạn hoàn toàn rủi ro mà không còn tiền mặt.

5. **Không thoát từng phần**: Trailing TP bán 100% vị thế. Không có khái niệm chốt lời từng phần hay thoát dần, điều có thể có lợi hơn trong một số tình huống.

6. **Rủi ro gap**: Trong crypto, flash crash có thể xuyên qua tất cả các mức safety order trong vài phút. Bạn có thể đi từ điểm vào đến -35% ngay lập tức, triển khai toàn bộ vốn ở một mức giá (xấu) duy nhất.

## Điều Kiện Thị Trường Lý Tưởng

- **Tốt nhất**: Các đợt giảm mạnh theo sau bởi hồi phục chữ V (flash crash, sự kiện FUD đảo chiều)
- **Tốt**: Dao động đều đặn với biên độ 5-15%
- **Kém**: Giảm chậm và đều (safety order kích hoạt từng cái, không hồi phục)
- **Tệ nhất**: Thị trường gấu kéo dài (vốn được triển khai tối đa ở giá tệ nhất)

## Kết Quả Đấu Trường (Backtest BTC/USDT 7 ngày)

```
Market: $80,267 -> $78,088 (-2.72%)
TrailingDCA:  ROI -0.28%  |  Alpha +2.43%  |  1 trade  |  Cost $0.24
```

Xếp thứ 2 trong đấu trường -- về cơ bản hòa với Grid+DCA. Tuy nhiên, đây là kết quả gây hiểu lầm: chiến lược chủ yếu đứng yên (chỉ có lệnh cơ sở $200 được đầu tư). $1,800 còn lại nằm trong USDT, điều này tự nhiên bảo vệ giá trị danh mục trong đợt giảm. Theo một nghĩa nào đó, TrailingDCA "thắng" bằng cách không chơi.

## Bot Tương Đương

| Bot | Tên Tính Năng | Khác Biệt Chính |
|-----|-------------|----------------|
| **3Commas** | DCA Bot | Bản gốc; hỗ trợ long/short, tín hiệu TradingView |
| **Pionex** | DCA Bot | Giao diện đơn giản hơn, tích hợp sẵn trong sàn |
| **Bitsgap** | DCA Bot | Chế độ trailing, view danh mục tích hợp |
| **Cornix** | DCA Bot | Tích hợp Telegram cho các nhóm tín hiệu |

## Khi Nào Nên Dùng

Dùng TrailingDCA khi bạn kỳ vọng thị trường **biến động nhưng cuối cùng phục hồi**. Lý tưởng cho:
- Giao dịch altcoin có các đợt giảm mạnh nhưng có xu hướng bật lại
- Giữ trong các giai đoạn vĩ mô không chắc chắn (safety order mua khi sợ hãi)
- Chạy song song với grid bot như chiến lược "bảo hiểm crash"

Tránh nó trong các đợt giảm chậm chạp hoặc trong thị trường rất yên ả nơi safety order không bao giờ kích hoạt và vốn ngồi không.

## Ý Tưởng Tối Ưu Hóa

1. **Safety deviation chặt hơn** cho BTC (ví dụ: [1.5, 3, 6, 10, 15]) vì BTC ít biến động hơn altcoin
2. **Nhiều chu kỳ**: Cho phép bot khởi động lại sau TP thay vì chờ đủ thời gian
3. **Điều chỉnh scale factor**: 1.5x là tích cực; 1.2x an toàn hơn cho ngân sách lớn
4. **Thoát theo thời gian**: Nếu không có TP sau X giờ, giảm kích thước vị thế thay vì giữ vô thời hạn
