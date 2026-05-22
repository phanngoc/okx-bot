# Tổng Quan So Sánh Các Chiến Lược

## Đấu Trường (The Arena)

Năm chiến lược chủ động + benchmark Buy&Hold cạnh tranh trực tiếp trên cùng một dữ liệu giá lịch sử. Tất cả chiến lược đều bắt đầu với cùng một ngân sách ($2,000), cùng một giá vào lệnh, và cùng một mô hình phí (mức phí spot của OKX).

## So Sánh Nhanh

| Chiến Lược | Loại | Lấy Cảm Hứng Từ | Giao Dịch/Tuần | Chi Phí TB | Thị Trường Tốt Nhất |
|----------|------|-------------|-------------|----------|-------------|
| Grid+DCA | Cơ học | Pionex, Bitsgap | 140+ | $5-6 | Đi ngang (sideways) |
| TrailingDCA | Theo sự kiện | 3Commas | 1-10 | $0-2 | Hồi phục chữ V |
| BB_Breakout | Momentum | Bollinger/Carter | 5-15 | $3-5 | Bứt phá sau squeeze |
| MeanRevert | Trái chiều | Stat arb, Hummingbot | 8-15 | $4-6 | Đi trong biên độ |
| Debate | Dùng AI | Research (MIT 2023) | 8-15 | $3-5 | Theo tin tức |
| Buy&Hold | Bị động | Buffett, Bogle | 0 | $0 | Thị trường tăng |

## Kết Quả Đấu Trường (BTC/USDT 7 ngày, thị trường -2.72%)

```
Rank  Strategy       ROI        Alpha     Trades  Cost
#1    MeanRevert    +0.46%     +3.18%     10     $5.31
#2    TrailingDCA   -0.28%     +2.43%      1     $0.24
#3    Grid+DCA      -0.28%     +2.43%    144     $5.66
#4    BB_Breakout   -0.37%     +2.34%      8     $3.59
#5    Debate        -0.84%     +1.87%     12     $3.54
#6    Buy&Hold      -2.72%      0.00%      0     $0.00
```

## DNA Của Từng Chiến Lược

### Theo Chế Độ Thị Trường

```
                 Bull Rally    Sideways     Bear Dip     Crash
Grid+DCA         Kém           TỐT NHẤT     Tốt          Kém
TrailingDCA      Khá           Khá          Tốt          TỐT NHẤT (nếu hồi V)
BB_Breakout      TỐT NHẤT      Kém          Kém          Kém
MeanRevert       Kém           TỐT NHẤT     Tốt          Khá
Debate           Khá           Khá          Khá          Khá
Buy&Hold         TỐT NHẤT      Kém          Kém          Kém
```

### Theo Nguồn Tín Hiệu

| Chiến Lược | Kỹ Thuật | Tin Tức | AI/LLM | Theo Thời Gian |
|----------|-----------|------|--------|------------|
| Grid+DCA | Mức giá | - | - | Khoảng cách DCA |
| TrailingDCA | Độ lệch giá | - | - | - |
| BB_Breakout | BB + RSI | - | - | - |
| MeanRevert | BB + RSI + ADX | - | - | - |
| Debate | RSI, MACD, BB, SMA, Vol, S/R | RSS feeds | Claude Haiku | Khoảng cách debate |
| Buy&Hold | - | - | - | - |

### Theo Hiệu Quả Phí

| Chiến Lược | Loại Lệnh | Mức Phí | Lợi Thế Phí |
|----------|-----------|----------|---------------|
| Grid+DCA | Limit (grid) + Market (DCA) | 0.08% / 0.12% | Phí mỗi giao dịch thấp nhất (grid) |
| TrailingDCA | Market | 0.12% | Tổng số giao dịch ít nhất |
| BB_Breakout | Market | 0.12% | Tần suất vừa phải |
| MeanRevert | Market | 0.12% | Tần suất vừa phải |
| Debate | Market | 0.12% | + Chi phí LLM (~$6/tuần) |
| Buy&Hold | Không có | 0% | Không có chi phí |

## Ma Trận Điểm Mạnh vs Điểm Yếu

| Chiến Lược | Điểm Mạnh Cốt Lõi | Điểm Yếu Cốt Lõi |
|----------|--------------|---------------|
| Grid+DCA | Sinh lời từ MỌI dao động | Thua lỗ trong xu hướng mạnh |
| TrailingDCA | Bắt được crash-rồi-bật | Bất động trong thị trường yên ả |
| BB_Breakout | Bắt được những cú bứt phá lớn | Bứt phá giả giết chết lợi nhuận |
| MeanRevert | Lợi thế thống kê trong biên độ | Sai khi đổi chế độ thị trường |
| Debate | Thích ứng với tin tức/ngữ cảnh | Chậm, không nhất quán, đắt đỏ |
| Buy&Hold | Không phí, hưởng trọn upside | Không bảo vệ khi giảm |

## Hồ Sơ Rủi Ro

| Chiến Lược | Rủi Ro Sụt Giảm Tối Đa | Vốn Có Rủi Ro | Tốc Độ Hồi Phục |
|----------|-------------------|-----------------|----------------|
| Grid+DCA | Trung bình (lệnh mua khớp, không có lệnh bán) | 65% grid + 35% DCA | Chậm (cần định lại giá grid) |
| TrailingDCA | Cao (mở rộng kiểu Martingale) | Tối đa 100% nếu tất cả safety order kích hoạt | Trung bình (reset sau TP) |
| BB_Breakout | Thấp (vị thế 25% + stop 3%) | Tối đa 0.75% mỗi giao dịch | Nhanh (stop nhanh + vào lại) |
| MeanRevert | Trung bình (20% mỗi vị thế, tối đa 5) | Tối đa 100% nếu tất cả 5 vị thế mở | Trung bình (chờ hồi về trung bình) |
| Debate | Trung bình (5-40% mỗi giao dịch) | Phụ thuộc vào quyết định LLM | Khó dự đoán |
| Buy&Hold | Tối đa (100% luôn đầu tư) | 100% | Phụ thuộc chu kỳ thị trường |

## Các Cặp Bổ Trợ

Những chiến lược sau bổ trợ cho nhau khi chạy cùng lúc:

**Grid+DCA + MeanRevert**: Grid sinh lời từ những dao động nhỏ; MeanRevert bắt những cú bật lớn hơn khi quá bán. Cùng nhau chúng bao quát cả range trading vi mô và vĩ mô.

**TrailingDCA + BB_Breakout**: TrailingDCA sinh lời từ các đợt crash (safety order mua đáy); BB_Breakout sinh lời từ hồi phục (bắt bứt phá sau crash). Chúng bao quát cả hai mặt của hình chữ V.

**Debate + Bất kỳ**: Bot Debate cung cấp một lớp "giống con người". Có thể dùng làm bộ lọc xác nhận: chỉ giao dịch khi cả chiến lược theo quy tắc VÀ debate đều đồng ý.

## 2 Tháng Sẽ Cho Chúng Ta Biết Điều Gì

Sau 60 ngày chạy đấu trường hàng ngày, chúng ta sẽ biết:

1. **Tỷ lệ thắng**: Mỗi chiến lược về #1 với tần suất ra sao?
2. **Tính nhất quán**: Độ lệch chuẩn của ROI giữa các phiên
3. **Phụ thuộc chế độ**: MeanRevert có luôn thắng trong thị trường đi ngang? Grid+DCA có thống trị trong thị trường dao động?
4. **Gánh nặng phí**: Các chiến lược tần suất cao (Grid) có mất đi lợi thế theo thời gian do phí tích lũy?
5. **Giá trị LLM**: Bot Debate có cải thiện khi có thêm dữ liệu, hay nó luôn là yếu nhất?
6. **Danh mục tối ưu**: Phân bổ giữa các chiến lược như thế nào để tối đa hóa lợi nhuận điều chỉnh theo rủi ro?

## Tham Khảo File

| Tài Liệu | Chiến Lược |
|----------|----------|
| [01_grid_dca.md](01_grid_dca.md) | Grid + DCA |
| [02_trailing_dca.md](02_trailing_dca.md) | Trailing DCA |
| [03_bollinger_breakout.md](03_bollinger_breakout.md) | Bollinger Breakout |
| [04_mean_reversion.md](04_mean_reversion.md) | Mean Reversion |
| [05_debate_agent.md](05_debate_agent.md) | Multi-Agent Debate |
| [06_buy_and_hold.md](06_buy_and_hold.md) | Buy & Hold (Benchmark) |
