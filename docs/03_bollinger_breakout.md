# Chiến Lược Bollinger Band Breakout

## Nguồn Gốc

Bollinger Bands được phát triển bởi **John Bollinger** vào những năm 1980 và xuất bản trong cuốn sách năm 2001 *Bollinger on Bollinger Bands*. Khái niệm "squeeze" -- khi các dải hẹp lại báo hiệu chuyển động bùng nổ -- đã trở thành mô hình giao dịch rộng rãi, đặc biệt sau khi **John Carter** phổ biến chỉ báo TTM Squeeze.

Trong giao dịch crypto, **Bitsgap**, **TradeSanta**, và **Quadency** đều cung cấp bot dựa trên Bollinger. Biến thể breakout đặc biệt phù hợp với crypto vì xu hướng của loại tài sản này là nén biến động theo sau bởi các chuyển động bùng nổ.

## Cách Hoạt Động

### Lý Thuyết: Biến Động Hồi Về Trung Bình

Bollinger Bands đo biến động bằng độ lệch chuẩn. Khi các dải hẹp lại (biến động thấp), nghĩa là thị trường đang "cuộn lại" -- tích tụ áp lực cho một chuyển động có hướng. Như một lò xo bị nén, càng nén chặt, sự bùng nổ cuối cùng càng mạnh.

```
BB Width = (Upper Band - Lower Band) / Middle Band * 100

Rộng (>4%):     Biến động cao, thị trường sôi động
Bình thường (2-4%): Điều kiện trung bình
Squeeze (<2%):  Nén, breakout sắp xảy ra
```

### Bước 1: Phát Hiện Squeeze

Bot liên tục theo dõi BB width. Khi `width_pct < 2.0%` (ngưỡng squeeze), nó đặt `in_squeeze = True`. Đây là giai đoạn cảnh báo -- một breakout đang được chờ đợi.

### Bước 2: Xác Nhận Breakout

Khi đã trong squeeze, bot theo dõi giá phá lên trên upper band **VÀ** RSI > 50 (xác nhận momentum tăng). Cả hai điều kiện phải đúng:

```python
if self.in_squeeze and self.position_side is None:
    if price > bb["upper"] and rsi > 50:
        # BREAKOUT ĐƯỢC XÁC NHẬN -> MUA
```

Khi xác nhận, bot mua với 25% tổng ngân sách.

### Bước 3: Quản Lý Vị Thế

Khi đã vào vị thế, ba điều kiện thoát được theo dõi:

1. **Stop Loss (3%)**: Nếu giá giảm 3% từ điểm vào, bán 100% ngay lập tức
   ```
   Entry: $80,000 -> Stop tại $77,600
   ```

2. **Take-Profit Từng Phần**: Nếu giá trên upper BB VÀ RSI > 75 (quá mua), bán 60% vị thế
   ```
   Chốt lợi nhuận trong khi vẫn giữ 40% rủi ro cho upside thêm
   ```

3. **Thoát Khi Hồi Về Trung Bình**: Nếu giá giảm xuống dưới middle band, bán 100%
   ```
   Breakout đã thất bại -- giá đã hồi về trung bình
   ```

### Bước 4: Reset Phát Hiện Squeeze

Khi BB width vượt quá `squeeze_threshold * 1.5` (3.0%), cờ squeeze reset. Điều này ngăn việc vào lại quá nhanh sau một breakout giả.

## Tham Số

| Tham Số | Giá Trị | Mô Tả |
|-----------|-------|-------------|
| `bb_period` | 20 | Chu kỳ lookback của Bollinger Band |
| `bb_std` | 2.0 | Độ lệch chuẩn cho các dải |
| `squeeze_threshold` | 2.0% | BB width dưới mức này = squeeze |
| `rsi_period` | 14 | Chu kỳ lookback của RSI |
| `position_pct` | 25% | Ngân sách mỗi vị thế |
| `stop_loss_pct` | 3.0% | Lỗ tối đa trước khi thoát |

## Mô Hình Phí

Tất cả lệnh đều là **lệnh market**: phí taker 0.10% + slippage 0.02% = 0.12% mỗi giao dịch. Chiến lược giao dịch ở mức vừa phải -- 8 giao dịch trong thử nghiệm 7 ngày, chủ yếu là cặp entry + stop-loss hoặc entry + thoát hồi trung bình.

## Điểm Mạnh

1. **Bắt được những chuyển động bùng nổ**: Khi một breakout thực sự xảy ra sau một squeeze dài, chuyển động có thể đạt 5-15% trong một ngày. Chiến lược được thiết kế để có vị thế chính xác khi điều này xảy ra.

2. **Quản lý rủi ro rõ ràng**: Stop loss 3% giới hạn downside mỗi giao dịch. Với kích thước vị thế 25%, lỗ tối đa mỗi giao dịch là:
   ```
   25% ngân sách * 3% stop loss = 0.75% tổng danh mục
   ```

3. **Chốt lời từng phần**: Bán 60% từng phần khi quá mua chốt lợi nhuận trong khi vẫn giữ 40% rủi ro. Điều này cân bằng giữa tham lam và thận trọng.

4. **Vật lý của biến động**: Biến động là một trong số ít thuộc tính hồi về trung bình trong thị trường tài chính. Biến động thấp *thực sự* báo hiệu biến động cao -- điều này được chứng minh thực nghiệm trong tất cả các loại tài sản.

5. **Hoạt động ở cả hai hướng**: Mặc dù triển khai của chúng ta chỉ long, mô hình squeeze hoạt động cho cả breakout và breakdown. (Phiên bản gấu có thể short khi breakout xuống.)

6. **Tần suất giao dịch vừa phải**: 8 giao dịch trong 7 ngày nghĩa là khoảng 1 giao dịch mỗi ngày. Đủ thấp để phí thấp, đủ cao để bắt cơ hội.

## Điểm Yếu

1. **Breakout giả là sát thủ**: Vấn đề số 1. Giá phá lên trên upper band, bot mua, sau đó giá đảo chiều ngay vào trong. Stop loss kích hoạt ở -3%, và bot thua. Trong crypto, breakout giả xảy ra thường xuyên, đặc biệt quanh các mức kháng cự.

   Trong thử nghiệm đấu trường, chiến lược có **ROI âm (-0.37%)** -- có thể nhiều breakout giả chạm stop loss.

2. **Chỉ báo trễ**: Bollinger Bands được tính từ giá quá khứ. Đến lúc squeeze được phát hiện và breakout xác nhận, chuyển động có thể đã hoàn thành một phần. Bạn mua sau cú nổ ban đầu.

3. **Giới hạn chỉ long**: Trong thị trường gấu với breakout xuống, chiến lược ngồi không. Nó chỉ có thể sinh lời từ chuyển động lên, bỏ lỡ nửa số cơ hội breakout.

4. **Bộ lọc RSI thô**: RSI > 50 làm xác nhận khá lỏng lẻo. Trong thị trường rung lắc, RSI dao động quanh 50 nhanh chóng, gây nhiều tín hiệu giả. Bộ lọc mạnh hơn (như xác nhận volume hoặc phân tích đa khung thời gian) sẽ giảm tín hiệu giả.

5. **Proxy volume yếu**: Triển khai của chúng ta dùng proxy thay đổi giá thay vì dữ liệu volume thực. Dữ liệu volume thực sẽ cải thiện đáng kể việc xác nhận breakout. Phương thức `_volume_proxy()` ước lượng volume bằng cách đo độ lớn chuyển động giá gần đây so với trung bình -- điều này tương quan nhưng không bằng volume thực.

6. **Một khung thời gian duy nhất**: Bot chỉ phân tích nến 1 giờ. Các trader breakout chuyên nghiệp thường xác nhận trên nhiều khung thời gian (ví dụ: squeeze ngày + breakout giờ để vào).

## Điều Kiện Thị Trường Lý Tưởng

- **Tốt nhất**: Tích lũy kéo dài (1-2 tuần biến động thấp) theo sau bởi xúc tác tin tức hoặc breakout kỹ thuật
- **Tốt**: Thị trường có xu hướng với các pause tích lũy đều đặn
- **Kém**: Thị trường rung lắc với breakout giả thường xuyên (điều kiện crypto phổ biến nhất)
- **Tệ nhất**: Thị trường gấu chậm với breakout xuống (không thể sinh lời từ phía short)

## Kết Quả Đấu Trường (Backtest BTC/USDT 7 ngày)

```
Market: $80,267 -> $78,088 (-2.72%)
BB_Breakout:  ROI -0.37%  |  Alpha +2.34%  |  8 trades  |  Cost $3.59
```

Xếp thứ 4 trong đấu trường. ROI âm cho thấy nhiều breakout giả chạm stop loss. Tuy nhiên, chiến lược vẫn tạo ra +2.34% alpha so với Buy&Hold vì nó chủ yếu ở dạng tiền mặt (75% ngân sách không bao giờ triển khai) trong đợt giảm.

### Phân Tích Mẫu Giao Dịch

Từ các báo cáo định kỳ:
- **28h**: 0 giao dịch -- chờ squeeze
- **56h**: 2 giao dịch -- nỗ lực breakout đầu tiên
- **84h**: 2 giao dịch -- không có hành động mới (vẫn trong cùng vị thế hoặc bị stop out)
- **112h**: 4 giao dịch -- nhiều nỗ lực hơn, ROI giảm xuống -0.52%
- **140h**: 8 giao dịch -- tiếp tục lặp đi lặp lại, thua trên các breakout giả

Mẫu cho thấy chiến lược cố gắng vào nhiều breakout nhưng cứ bị stop out.

## Bot Tương Đương

| Bot | Tên Tính Năng | Khác Biệt Chính |
|-----|-------------|----------------|
| **TradeSanta** | Triggers dựa trên Bollinger | Một phần của hệ thống tín hiệu kết hợp |
| **Bitsgap** | Bot Phân Tích Kỹ Thuật | Kết hợp BB với các chỉ báo khác |
| **Quadency** | Smart Trading | BB breakout là một trong nhiều chiến lược dựng sẵn |
| **TradingView** | Cảnh báo chiến lược | Cảnh báo BB squeeze kích hoạt bot bên ngoài |

## Khi Nào Nên Dùng

Dùng Bollinger Breakout khi:
- Thị trường đã ở trong biên độ chặt >1 tuần (nhìn vào BB width ngày)
- Bạn muốn bắt đầu của một xu hướng mới
- Bạn có kiên nhẫn với breakout giả (chi phí stop loss là "phí bảo hiểm" bạn trả)

Tránh nó khi:
- Thị trường đã biến động cao (không có squeeze để break ra)
- Bạn cần lợi nhuận ổn định (chiến lược này có giai đoạn dài đứng yên xen kẽ với các cú thắng lớn hoặc thua nhỏ)
- Bạn đang trong thị trường gấu xác nhận (breakout chỉ long không hoạt động)

## Ý Tưởng Tối Ưu Hóa

1. **Thêm xác nhận volume**: Dùng dữ liệu volume thực từ sàn, yêu cầu volume 1.5x trung bình để xác nhận breakout
2. **Đa khung thời gian**: Yêu cầu BB squeeze ngày trước khi tìm điểm vào breakout giờ
3. **Stop loss thích ứng**: Dùng ATR (Average True Range) thay vì 3% cố định cho kích thước stop loss động
4. **Breakout phía short**: Thêm khả năng short khi giá phá xuống dưới lower BB sau squeeze
5. **Lọc theo xu hướng**: Chỉ vào breakout long khi MA 50 chu kỳ đang tăng (bộ lọc theo xu hướng)
