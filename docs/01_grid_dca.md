# Chiến Lược Grid + DCA

## Nguồn Gốc

Grid Trading được phổ biến bởi **Pionex** (2019) và sau đó được áp dụng bởi **Bitsgap**, **3Commas**, và **KuCoin Bot**. Khái niệm này có từ thị trường forex truyền thống, nơi các trader đặt lệnh mua/bán ở các khoảng giá cố định để kiếm lời từ chuyển động trong biên độ. DCA (Dollar Cost Averaging - bình quân giá) là một trong những chiến lược đầu tư cổ xưa nhất, được Benjamin Graham hệ thống hóa trong cuốn *The Intelligent Investor* (1949).

Triển khai của chúng ta kết hợp cả hai: một lưới (grid) các lệnh limit để bắt biến động đi ngang, trong khi các lệnh DCA mua market định kỳ cung cấp khả năng tích lũy ổn định bất kể hướng giá.

## Cách Hoạt Động

### Thành Phần Grid (65% ngân sách)

1. Khi khởi tạo, chiến lược tính toán biên độ giá: `entry_price +/- 5%`
2. Biên độ này được chia thành 20 mức bằng nhau (đường lưới)
3. **Lệnh mua** được đặt dưới giá vào, **lệnh bán** ở trên
4. Mỗi lệnh grid sử dụng $50 USDT
5. Khi một lệnh mua khớp, một lệnh bán mới được đặt ở mức lưới phía trên (và ngược lại)
6. Lệnh grid là **lệnh limit** = **phí maker (0.08%)**, không có slippage

Grid sinh lời từ chênh lệch giữa mức mua và mức bán. Với giá BTC $80,000 và biên độ 5%, mỗi mức lưới cách nhau ~$400. Mỗi chu kỳ mua-bán hoàn chỉnh trên một mức kiếm được khoảng:

```
$400 spread / $80,000 price = 0.5% gộp mỗi chu kỳ
- 0.08% phí maker (mua) - 0.08% phí maker (bán) = 0.34% ròng mỗi chu kỳ
```

### Thành Phần DCA (35% ngân sách)

1. Mỗi 4 giờ, đặt một **lệnh mua market** $30 USDT
2. Sử dụng **phí taker (0.10%)** + **slippage (0.02%)**
3. Cung cấp tích lũy ổn định theo lịch
4. Không có logic bán -- DCA chỉ tích lũy

### Phân Bổ Ngân Sách

```
Tổng Ngân Sách: $2,000
  Grid: $1,300 (65%) -- 26 mức grid @ $50 mỗi cái
  DCA:  $700  (35%) -- ~58 lần mua @ $30 trong 72h+ (mỗi 4h)
```

## Tham Số

| Tham Số | Giá Trị | Mô Tả |
|-----------|-------|-------------|
| `price_range_pct` | 5.0% | Biên độ grid trên/dưới giá vào |
| `num_grids` | 20 | Số mức grid |
| `investment_per_grid` | $50 | USDT mỗi lệnh grid |
| `interval_hours` | 4.0 | Khoảng cách giữa các lần mua DCA |
| `amount_per_buy` | $30 | USDT mỗi lần mua DCA |

## Mô Hình Phí

| Loại Lệnh | Phí | Slippage | Tổng Chi Phí |
|------------|-----|----------|------------|
| Grid (limit) | 0.08% maker | Không | 0.08% |
| DCA (market) | 0.10% taker | 0.02% | 0.12% |

Lệnh grid rẻ hơn đáng kể vì chúng cung cấp thanh khoản cho sổ lệnh. Đây là lợi thế thực sự so với các chiến lược chỉ dùng lệnh market.

## Điểm Mạnh

1. **Ổn định trong thị trường đi ngang**: Mỗi dao động giá trong biên độ grid kích hoạt chu kỳ mua-bán, tạo ra lợi nhuận nhỏ bất kể hướng. Đây là lợi thế cốt lõi của chiến lược.

2. **Cấu trúc phí thấp**: Lệnh grid limit chỉ trả phí maker (0.08%), thấp nhất hiện có. Hầu hết chiến lược cạnh tranh phải trả phí taker (0.10%) + slippage.

3. **Kỷ luật cơ học**: Không có quyết định cảm tính, không có chỉ báo để hiểu sai. Grid thực thi một cách hệ thống.

4. **Tần suất giao dịch cao**: Trong thử nghiệm đấu trường 7 ngày, Grid+DCA thực hiện **144 giao dịch** -- nhiều hơn bất kỳ chiến lược nào khác. Mỗi giao dịch chốt một lợi nhuận nhỏ.

5. **Làm mượt với DCA**: Ngay cả khi biên độ grid sai, DCA vẫn đảm bảo tích lũy liên tục với giá trung bình.

6. **Tự bổ sung**: Khi lệnh mua grid khớp, lệnh bán mới được đặt; khi lệnh bán khớp, lệnh mua mới được đặt. Grid tự tái tạo chính nó.

## Điểm Yếu

1. **Thua lỗ trong xu hướng mạnh**: Nếu giá giảm 10%+ (xuyên qua đáy grid), tất cả lệnh mua khớp nhưng không có lệnh bán nào thực thi. Bạn sẽ ôm vị thế với giá trung bình cao hơn. Trong thử nghiệm, chiến lược âm (-0.28%) khi thị trường giảm 2.7%.

2. **Chi phí cơ hội trong các đợt tăng mạnh**: Nếu BTC nhảy 15%, grid bán hết vị thế sớm ở các mức thấp. Bạn chỉ bắt được lợi nhuận trong biên độ grid, bỏ lỡ phần lớn chuyển động. Buy&Hold sẽ vượt trội hơn rất nhiều.

3. **Yêu cầu vốn cao**: 20 mức grid với $50 mỗi cái khóa $1,000 trong lệnh chờ. Hiệu quả sử dụng vốn kém -- phần lớn ngân sách nằm im dưới dạng lệnh chưa khớp.

4. **Phụ thuộc biên độ**: Biên độ grid 5% là tùy ý. Nếu biến động 1%, grid không bao giờ kích hoạt. Nếu biến động 15%, grid cạn kiệt và trở thành công cụ tích lũy một chiều.

5. **DCA luôn mua**: Không có DCA bên bán. Trong thị trường gấu, DCA cứ tiếp tục mua khi giá giảm, làm tăng thua lỗ.

6. **Phí tích lũy do tần suất cao**: 144 giao dịch ở 0.08% mỗi cái = $5.66 tổng chi phí. Mặc dù mỗi giao dịch rẻ, nhưng khối lượng cộng dồn lại đáng kể.

## Điều Kiện Thị Trường Lý Tưởng

- **Tốt nhất**: Thị trường đi ngang/biên độ với dao động 3-8% (rung lắc, không có xu hướng rõ ràng)
- **Tốt**: Xu hướng tăng nhẹ với các đợt điều chỉnh đều đặn
- **Kém**: Xu hướng giảm mạnh (lệnh mua khớp, bán không khớp)
- **Tệ nhất**: Tăng giá parabol (bán sớm, bỏ lỡ hầu hết chuyển động)

## Kết Quả Đấu Trường (Backtest BTC/USDT 7 ngày)

```
Market: $80,267 -> $78,088 (-2.72%)
Grid+DCA:  ROI -0.28%  |  Alpha +2.43%  |  144 trades  |  Cost $5.66
```

Grid+DCA xếp thứ 3 trong đấu trường nhưng tạo ra alpha lớn so với Buy&Hold (+2.43%). Chiến lược bảo vệ vốn tốt hơn nhiều so với việc giữ trong đợt giảm. Số lượng giao dịch cao cho thấy nó đang chủ động chốt các lợi nhuận nhỏ trong suốt thời gian.

## Bot Tương Đương

| Bot | Tên Tính Năng | Khác Biệt Chính |
|-----|-------------|----------------|
| **Pionex** | Grid Trading Bot | Hỗ trợ grid cấp số cộng + cấp số nhân |
| **Bitsgap** | GRID Bot | Có "trailing up" để dịch chuyển grid theo xu hướng |
| **3Commas** | Grid Bot | Tích hợp với 18+ sàn giao dịch |
| **KuCoin** | Spot Grid | Đề xuất tham số bằng AI dựa trên biến động |

## Khi Nào Nên Dùng

Dùng Grid+DCA khi bạn tin rằng thị trường sẽ **đi trong biên độ** trong tương lai gần. Đây là chiến lược "nhàm chán nhưng đáng tin cậy" -- nó không thắng lớn, nhưng cũng không thua lớn. Sự kết hợp giữa grid trading (lợi nhuận từ dao động) và DCA (lợi nhuận từ mua bình quân theo thời gian) cung cấp cách tiếp cận cân bằng.

Tránh nó khi bạn có niềm tin định hướng mạnh. Nếu bạn nghĩ BTC sẽ tăng 20%, chỉ cần mua và giữ. Nếu bạn nghĩ nó sẽ crash 20%, hãy ở trong USDT.
