# Buy & Hold (Benchmark)

## Nguồn Gốc

Buy & Hold là chiến lược đầu tư cổ xưa nhất, được ủng hộ bởi **Warren Buffett**, **John Bogle** (người sáng lập Vanguard), và **Burton Malkiel** (*A Random Walk Down Wall Street*, 1973). Lý thuyết thị trường hiệu quả (EMH) lập luận rằng vì thị trường tổng hợp tất cả thông tin có sẵn, giao dịch chủ động không thể nhất quán vượt qua cách tiếp cận mua-và-giữ đơn giản sau khi tính phí.

Trong đấu trường crypto, Buy & Hold đóng vai trò **benchmark** -- bất kỳ chiến lược nào không thể đánh bại nó đang phá hủy giá trị so với việc đơn giản mua và ngồi.

## Cách Hoạt Động

```
Bước 1: Mua $2,000 BTC ở giá vào
Bước 2: Giữ trong toàn bộ thời gian
Bước 3: Tính giá trị danh mục cuối ở giá thoát
```

Thế thôi. Không có chỉ báo, không có quyết định, không có giao dịch, không có phí.

```python
bh_qty = budget / entry_price    # vd: 2000 / 80267 = 0.02492 BTC
bh_pv = bh_qty * final_price     # vd: 0.02492 * 78088 = $1,945.69
bh_roi = (bh_pv - budget) / budget * 100  # = -2.72%
```

## Tham Số

Không có. Đây là chiến lược không-tham-số.

## Mô Hình Phí

**Không phí, không slippage.** Điều này thực ra hơi không thực tế -- Buy & Hold thực sự sẽ chịu một lần phí taker (0.10%) và slippage (0.02%) trên lệnh mua ban đầu. Đối với vị thế $2,000, đó là ~$2.40 tổng chi phí. Chúng ta bỏ qua điều này vì Buy & Hold được dùng như benchmark lý tưởng hóa.

## Điểm Mạnh

1. **Bắt 100% bất kỳ xu hướng tăng nào**: Nếu BTC tăng 50% trong một tháng, Buy & Hold bắt được toàn bộ 50%. Không có chiến lược nào lấy vị thế từng phần hoặc thoát sớm có thể sánh được trong bull run mạnh.

2. **Không phí**: Không giao dịch nghĩa là không ma sát. Qua thời gian dài, điều này tích lũy đáng kể. Một chiến lược giao dịch 10 lần/ngày ở 0.12% mỗi giao dịch trả ~1.2% phí hàng ngày -- qua một tháng, đó là 36% mất vào chi phí giao dịch. Buy & Hold không trả gì.

3. **Không có quyết định cảm tính**: Không bán quá sớm, không mua quá muộn, không thoát hoảng loạn. Chiến lược miễn nhiễm với thiên kiến tài chính hành vi.

4. **Vượt trội về mặt lịch sử**: Qua 15 năm lịch sử của Bitcoin, Buy & Hold là chiến lược tốt nhất cho bất kỳ thời gian giữ nào > 4 năm. Từ 2009 đến 2025, BTC đi từ $0 đến $80,000+. Bất kỳ giao dịch chủ động nào trong giai đoạn đó gần như chắc chắn thua kém giữ.

5. **Không phức tạp vận hành**: Không có server để chạy, không có API key, không có chi phí LLM, không cần giám sát. Cách tiếp cận "set and forget" tối thượng.

6. **Benchmark cho alpha**: Alpha được định nghĩa là `strategy_ROI - buyhold_ROI`. Bất kỳ alpha dương nào nghĩa là chiến lược đã thêm giá trị vượt qua việc giữ đơn giản.

## Điểm Yếu

1. **100% rủi ro trước drawdown**: Nếu BTC giảm 70% (như đã từng năm 2022), Buy & Hold giảm 70%. Không có quản lý rủi ro, không có stop loss, không có cân bằng lại. Trong thử nghiệm đấu trường của chúng ta, cú giảm thị trường -2.72% trở thành lỗ danh mục -2.72% -- tệ nhất trong tất cả các chiến lược.

2. **Không chốt lời**: Ngay cả khi danh mục tăng 100%, Buy & Hold không bao giờ bán. Nó có thể đi cùng cú tăng khổng lồ suốt đường về breakeven hoặc thấp hơn.

3. **Chi phí cơ hội trong thị trường đi ngang**: Trong thị trường sideways, vốn bị khóa không làm gì. Các chiến lược như Grid+DCA và MeanReversion chủ động sinh lời từ dao động giá trong các giai đoạn này.

4. **Yêu cầu chân trời thời gian vô hạn**: Buy & Hold chỉ hoạt động đáng tin cậy nếu bạn có thể giữ "mãi mãi". Trong bất kỳ khung thời gian hữu hạn nào, bạn có thể mua ở đỉnh và thoát ở đáy. Cửa sổ đấu trường 7 ngày chính xác là tình huống này.

5. **Không thích ứng**: Nếu điều kiện cơ bản thay đổi (sàn bị hack, lệnh cấm quy định), Buy & Hold không phản ứng. Nó là đối lập chính xác của các chiến lược thích ứng như bot Debate.

## Điều Kiện Thị Trường Lý Tưởng

- **Tốt nhất**: Thị trường bull mạnh, bền vững (tăng giá parabol)
- **Tốt**: Xu hướng tăng nhẹ qua thời gian dài (nhiều năm)
- **Kém**: Thị trường đi ngang/biên độ (vốn chết, chiến lược chủ động làm tốt hơn)
- **Tệ nhất**: Thị trường gấu / crash (rủi ro hoàn toàn trước tất cả tổn thất)

## Kết Quả Đấu Trường (Backtest BTC/USDT 7 ngày)

```
Market: $80,267 -> $78,088 (-2.72%)
Buy&Hold:  ROI -2.72%  |  Alpha +0.00%  |  0 trades  |  Cost $0
```

**Bét bảng.** Mọi chiến lược chủ động đều đánh bại Buy & Hold trong giai đoạn này. Alpha +2-3% từ các chiến lược chủ động đại diện cho giá trị của giao dịch chiến thuật trong thị trường giảm.

### Tại Sao Buy & Hold Thua

Giai đoạn đấu trường là **một tuần hơi giảm**. BTC giảm 2.72% với biên độ khoảng $79K-$82K. Các chiến lược chủ động sinh lời từ:
- MeanReversion: mua các cú bật quá bán trong biên độ
- Grid+DCA: bắt các lợi nhuận nhỏ từ dao động grid
- TrailingDCA: bảo vệ vốn bằng cách giữ 90% trong USDT

Buy & Hold đầu tư toàn bộ từ giờ 0 và hấp thụ toàn bộ cú giảm.

### Khi Nào Buy & Hold Sẽ Thắng

Nếu BTC tăng 10% trong tuần (vd: $80K -> $88K):
- Buy & Hold: +10.00%
- MeanRevert: ~+2% (bộ lọc ADX sẽ chặn hầu hết giao dịch trong thị trường có xu hướng)
- Grid+DCA: ~+5% (grid bán sớm, bỏ lỡ phần trên)
- TrailingDCA: ~+3% (lệnh cơ sở nhỏ, safety orders không bao giờ kích hoạt trong xu hướng tăng)

Trong thị trường bull, Buy & Hold rất khó đánh bại.

## Câu Hỏi Thực Sự

Buy & Hold trả lời câu hỏi: **"Tôi có nên giao dịch chút nào không?"**

Nếu không có chiến lược nào nhất quán đánh bại Buy & Hold sau phí trong giai đoạn 2 tháng, câu trả lời là không -- bạn nên chỉ mua và giữ BTC.

Đây là lý do chúng ta chạy nó làm benchmark. Sau 60 ngày các phiên đấu trường hàng ngày, bảng xếp hạng sẽ cho thấy dứt khoát liệu giao dịch chủ động có thêm giá trị trong chế độ thị trường hiện tại.

## Bối Cảnh Lịch Sử: Bitcoin Buy & Hold

| Giai Đoạn | Biến Động Giá BTC | Chiến Lược Chủ Động Có Thắng Không? |
|--------|-----------------|------------------------------|
| 2017 (bull) | +1,300% | Không -- không chiến lược nào đánh bại được điều này |
| 2018 (bear) | -73% | Có -- bất kỳ quản lý rủi ro nào cũng giúp |
| 2019-2020 | +95% | Ranh giới -- phụ thuộc thời điểm |
| 2021 (bull) | +60% | Không -- momentum quá mạnh |
| 2022 (bear) | -65% | Có -- tín hiệu bán cứu vốn |
| 2023-2024 | +150% | Không -- buy and hold lại thắng |
| 2025 (hiện tại) | Đi ngang | Có -- chiến lược chủ động bắt được biên độ |

Mẫu: Buy & Hold thắng trong thị trường bull, chiến lược chủ động thắng trong thị trường bear/đi ngang. Thách thức là biết bạn đang ở chế độ nào.
