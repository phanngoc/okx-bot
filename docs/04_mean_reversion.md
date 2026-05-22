# Chiến Lược Mean Reversion

## Nguồn Gốc

Mean reversion (hồi về trung bình) là một trong những khái niệm cổ xưa nhất trong thống kê, được **Francis Galton** đưa ra vào năm 1886 với tên "regression toward the mean". Trong tài chính, ý tưởng là giá có xu hướng quay trở lại giá trị trung bình sau những độ lệch cực đoan. **Pairs trading** (chủ lực của các hedge fund từ những năm 1980 tại Morgan Stanley) và **statistical arbitrage** đều dựa trên mean reversion.

Trong crypto, **Hummingbot** (market maker mã nguồn mở) và **Freqtrade** (framework bot Python) đều triển khai chiến lược mean reversion. Cách tiếp cận này bản chất là trái chiều: mua khi người khác sợ hãi (quá bán), bán khi người khác tham lam (quá mua).

## Cách Hoạt Động

### Nguyên Tắc Cốt Lõi

Chiến lược mua khi giá "quá thấp" theo thống kê và bán khi "quá cao". Nó sử dụng hai tín hiệu xác nhận và một bộ lọc chế độ thị trường:

**Tín Hiệu Mua** (cả ba phải đúng):
1. RSI < 30 (quá bán -- momentum đã cạn kiệt phía xuống)
2. Giá <= Lower Bollinger Band (giá ở mức cực đoan thống kê -- 2 độ lệch chuẩn dưới trung bình)
3. ADX < 25 (thị trường đi ngang, không có xu hướng -- mean reversion hoạt động trong biên độ, không phải xu hướng)

**Tín Hiệu Bán** (một trong hai):
1. RSI > 70 (quá mua -- momentum đã cạn kiệt phía lên)
2. Giá >= Upper Bollinger Band (giá đã hồi vượt qua trung bình đến cực kia)

**Stop Khẩn Cấp**:
- Nếu giá giảm 3% dưới Lower Bollinger Band, bán 50% vị thế để giới hạn lỗ

### Bộ Lọc ADX (Tại Sao Quan Trọng)

Thành phần quan trọng nhất là **ADX proxy** lọc bỏ thị trường có xu hướng:

```
Logic ADX proxy:
  Biên độ giá trong 20 nến gần nhất > 5% -> ADX = 40 (CÓ XU HƯỚNG, không giao dịch)
  Biên độ giá trong 20 nến gần nhất > 3% -> ADX = 25 (RANH GIỚI, không giao dịch)
  Biên độ giá trong 20 nến gần nhất < 3% -> ADX = 15 (ĐI NGANG, cho phép giao dịch)
```

**Tại sao điều này quan trọng**: Mean reversion là SAI trong các xu hướng. Nếu BTC trong xu hướng giảm xác nhận, RSI 28 không có nghĩa là "sắp bật quá bán" -- nó có nghĩa là "xu hướng mạnh, có thể tiếp tục giảm thêm". Bộ lọc ADX ngăn chiến lược bắt dao rơi.

Trong thử nghiệm đấu trường, bộ lọc này là chìa khóa: chiến lược chỉ giao dịch trong các giai đoạn yên ả, đi ngang và đứng ngoài trong giai đoạn có xu hướng ở cuối (khi BTC giảm từ $80.5K xuống $78K).

### Quản Lý Vị Thế

```
Số vị thế tối đa: 5
Kích thước vị thế: 20% ngân sách mỗi lần vào ($400 mỗi cái)
Mức rủi ro tối đa: 100% ngân sách (5 * 20%)
```

Nhiều vị thế có thể mở đồng thời ở các mức giá khác nhau, cung cấp hiệu ứng bình quân tự nhiên.

## Tham Số

| Tham Số | Giá Trị | Mô Tả |
|-----------|-------|-------------|
| `bb_period` | 20 | Lookback của Bollinger Band |
| `rsi_period` | 14 | Lookback của RSI |
| `rsi_buy` | 30 | Mua dưới RSI này |
| `rsi_sell` | 70 | Bán trên RSI này |
| `position_pct` | 20% | Ngân sách mỗi vị thế |
| `max_positions` | 5 | Số vị thế đồng thời tối đa |

## Mô Hình Phí

Tất cả lệnh đều là **lệnh market**: phí taker 0.10% + slippage 0.02% = 0.12% mỗi giao dịch. Chiến lược thực hiện 10 giao dịch trong 7 ngày -- tần suất vừa phải. Tổng chi phí: $5.31.

## Điểm Mạnh

1. **Thắng đấu trường**: MeanRevert là chiến lược duy nhất có **ROI dương (+0.46%)** trong thị trường -2.72%. Điều này đáng kể -- trong thị trường giảm, nó không chỉ thua ít hơn, mà thực sự kiếm tiền.

2. **Lợi thế thống kê đã được khẳng định**: Mean reversion là một trong số ít hiện tượng thị trường có nền tảng học thuật mạnh. Giá thực sự hồi về trung bình trong thị trường đi ngang. Đây không phải là hy vọng dựa trên khớp mẫu -- đó là thuộc tính thống kê của chuỗi thời gian tài chính.

3. **Bộ lọc ADX ngăn lỗi đi theo xu hướng**: Sát thủ lớn nhất của các chiến lược mean reversion là giao dịch ngược xu hướng mạnh. Bộ lọc ADX xác định chính xác khi nào nên đứng ngoài, điều có thể quan trọng hơn việc biết khi nào nên giao dịch.

4. **Rủi ro/lợi nhuận bất đối xứng**: Mua tại Lower Bollinger Band nghĩa là bạn mua với mức giảm giá 2 độ lệch chuẩn. Nếu phân phối thống kê đúng, có ~95% xác suất giá sẽ hồi về trên lower band.

5. **Bình quân nhiều vị thế**: Bằng cách cho phép tối đa 5 vị thế, chiến lược tự nhiên bình quân vào các điều kiện quá bán. Nếu lần mua đầu tiên ở RSI 28 quá sớm, các lần mua tiếp theo ở RSI 22 và RSI 18 hạ giá trung bình.

6. **Quy tắc bán rõ ràng**: Bán ở RSI > 70 hoặc upper BB cung cấp điểm thoát cụ thể. Không có quyết định chủ quan "Tôi nghĩ đã đến lúc bán".

## Điểm Yếu

1. **Phụ thuộc phát hiện biên độ**: ADX proxy được đơn giản hóa -- nó dùng tính toán biên độ giá thô thay vì chỉ báo ADX thực. Điều này có thể bỏ lỡ các thị trường có xu hướng trông yên ả trên cửa sổ 20 nến nhưng rõ ràng có xu hướng trên khung thời gian dài hơn.

2. **Nguy hiểm khi đổi chế độ**: Mean reversion hoạt động cho đến khi không. Khi thị trường chuyển từ đi ngang sang có xu hướng (ví dụ: sau sự kiện tin tức lớn), các lệnh mua "quá bán" của chiến lược trở thành giao dịch thua trong xu hướng mới.

3. **Vấn đề "bắt dao rơi"**: Ngay cả với bộ lọc ADX, có những tình huống bộ lọc hiển thị "đi ngang" nhưng một cú crash nhanh đang phát triển. Stop khẩn cấp 3% giúp ích nhưng chỉ sau khi bạn đã thua.

4. **Chậm trong thị trường có xu hướng**: Nếu BTC tăng 30%, chiến lược ngồi trong USDT toàn bộ thời gian (ADX > 25, không giao dịch). Buy&Hold sẽ vượt trội hơn rất nhiều trong các đợt bull run.

5. **Ngưỡng RSI cố định**: RSI < 30 hoạt động khác nhau ở các khung thời gian khác nhau. Trên biểu đồ 1 giờ, RSI < 30 có thể hồi phục trong vài giờ. Trên biểu đồ ngày, có thể mất nhiều tuần. Ngưỡng cố định không thích ứng với khung thời gian.

6. **Bán hết khi quá mua**: Khi RSI > 70, chiến lược bán 100% vị thế. Nhưng trong xu hướng tăng mạnh (mà bộ lọc ADX có thể không bắt ngay), RSI > 70 có thể duy trì trong nhiều ngày khi giá vẫn tăng.

## Điều Kiện Thị Trường Lý Tưởng

- **Tốt nhất**: Thị trường rung lắc, đi trong biên độ với mức hỗ trợ/kháng cự rõ ràng. BTC giao dịch giữa $75K-$82K trong nhiều tuần. Mean reversion gần như "tiền miễn phí" trong môi trường này.
- **Tốt**: Xu hướng giảm nhẹ với các cú bật quá bán đều đặn (mỗi cú bật được tín hiệu mua bắt)
- **Kém**: Thị trường có xu hướng mạnh ở bất kỳ hướng nào (bộ lọc ADX giữ chiến lược đứng yên)
- **Tệ nhất**: Black swan crash xuyên qua tất cả các mức hỗ trợ (stop 3% quá rộng)

## Kết Quả Đấu Trường (Backtest BTC/USDT 7 ngày)

```
Market: $80,267 -> $78,088 (-2.72%)
MeanRevert:  ROI +0.46%  |  Alpha +3.18%  |  10 trades  |  Cost $5.31
```

**Người thắng đấu trường.** Hãy phân tích tại sao:

### Lịch Sử Giao Dịch
- **0-56h**: 0 giao dịch. Thị trường đi ngang nhẹ (+1.5% đến +2%), nhưng RSI không bao giờ chạm 30 và giá không bao giờ chạm lower BB. Chiến lược chờ.
- **84h**: 1 giao dịch. Giá giảm xuống $80,642 và RSI briefly chạm vùng quá bán. Chiến lược mua.
- **112h**: 4 giao dịch. Thị trường giảm xuống $79,361. Nhiều lệnh mua kích hoạt khi giá chạm lower BB nhiều lần. Giá trung bình được hạ xuống.
- **140h**: 5 giao dịch. Thị trường hồi phục lên $80,581. Một số lệnh bán kích hoạt ở RSI > 70 hoặc upper BB. ROI nhảy lên +1.18%.
- **168h (cuối)**: 10 giao dịch. Giá cuối $78,088. Một số lệnh bán muộn chốt lợi nhuận, nhưng cú giảm cuối làm giảm lợi nhuận chưa thực hiện.

Chiến lược xác định chính xác giai đoạn đi ngang (giờ 56-140) và giao dịch nó có lãi. Khi thị trường gãy ở cuối, nó đã chốt lợi nhuận trên các giao dịch trước.

## Bot Tương Đương

| Bot | Tên Tính Năng | Khác Biệt Chính |
|-----|-------------|----------------|
| **Hummingbot** | Pure Market Making | Dùng spread bid/ask thay vì BB/RSI |
| **Freqtrade** | Chiến lược tùy chỉnh | Python mã nguồn mở, có thể cấu hình cao |
| **Mudrex** | Strategy canvas | Trình dựng chiến lược trực quan với template mean reversion |
| **Cryptohopper** | Strategy Designer | Kết hợp nhiều tín hiệu chỉ báo |

## Khi Nào Nên Dùng

Dùng MeanReversion khi:
- Thị trường đã đi ngang >5 ngày không có xu hướng rõ ràng
- Biến động ngụ ý/thực hiện ở mức vừa phải (không quá thấp, không quá cao)
- Bạn thoải mái với việc trái chiều (mua dip khi tâm lý sợ hãi)
- Bạn muốn cách tiếp cận có cơ sở thống kê thay vì chạy theo momentum

Tránh nó khi:
- Một xu hướng rõ ràng đang hình thành (bull hoặc bear)
- Các sự kiện vĩ mô lớn được kỳ vọng (FOMC, CPI release, halving)
- Biến động cực kỳ cao (mean reversion thất bại trong hoảng loạn)

## Tại Sao Nó Thắng (Và Khi Nào Sẽ Không)

Thử nghiệm đấu trường diễn ra trong **tuần hơi giảm, đi ngang**. Đây là môi trường tối ưu của MeanReversion. Trong thị trường có xu hướng mạnh (bull run hoặc crash), chiến lược này có thể sẽ thua kém Grid+DCA hoặc thậm chí Buy&Hold.

ROI +0.46% trong thị trường -2.72% tương đương với **alpha +3.18%** -- cao nhất trong tất cả chiến lược. Nhưng một tuần không phải là mẫu có ý nghĩa thống kê. Qua 2 tháng đấu trường hàng ngày, bức tranh thực sự sẽ xuất hiện.

## Ý Tưởng Tối Ưu Hóa

1. **Tính ADX thực**: Thay proxy biên độ giá bằng công thức ADX thực (Directional Movement Index của Welles Wilder)
2. **Ngưỡng RSI động**: Dùng phần trăm RSI thay vì 30/70 cố định. Trong bull market, "quá bán" có thể là RSI 40.
3. **Vào theo Z-score**: Thay vì BB + RSI, dùng z-score giá > 2 làm tín hiệu (cách tiếp cận thuần thống kê)
4. **Thoát từng phần**: Bán 50% ở RSI 60, 50% còn lại ở RSI 70 -- bắt toàn bộ sự hồi về mà không trả lại tất cả lợi nhuận
5. **Thoát theo thời gian**: Nếu vị thế không chạm TP trong 48h, giảm 25% -- đừng giữ vị thế thua lỗ vô thời hạn
