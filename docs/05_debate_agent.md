# Chiến Lược Multi-Agent Debate

## Nguồn Gốc

Framework multi-agent debate bắt nguồn từ nghiên cứu AI, đặc biệt là **"Improving Factuality and Reasoning in Language Models through Multiagent Debate"** (Du et al., 2023, MIT). Bài báo cho thấy việc có nhiều LLM agent tranh luận từ các góc nhìn khác nhau tạo ra suy luận tốt hơn một agent đơn.

Áp dụng vào trading, điều này phản ánh cấu trúc của một **ủy ban đầu tư** chuyên nghiệp: một chuyên gia phân tích bull (luận điểm mua), một chuyên gia phân tích bear (luận điểm bán), và một portfolio manager (quyết định cuối cùng). Các hedge fund như Bridgewater Associates nổi tiếng dùng định dạng debate "minh bạch triệt để" này cho các quyết định đầu tư.

Không có nền tảng bot crypto hiện có nào cung cấp hệ thống debate được hỗ trợ bởi LLM. Chiến lược này là duy nhất với triển khai của chúng ta.

## Cách Hoạt Động

### Kiến Trúc: Ba Agent

```
         Chỉ Báo Kỹ Thuật + Tin Tức
                    |
            +-------+-------+
            |               |
        BULL AGENT      BEAR AGENT
        (tìm lý do      (tìm lý do
         để MUA)         để BÁN)
            |               |
            +-------+-------+
                    |
             MODERATOR AGENT
             (cân nhắc lập luận,
              quyết định cuối cùng)
                    |
            BUY / SELL / HOLD
```

### Agent 1: Bull Agent

**Thiên kiến**: Lạc quan. Chủ động tìm lý do để mua.

**Đầu vào**: Chỉ báo kỹ thuật (RSI, MACD, SMA, BB, volume, hỗ trợ/kháng cự) + tâm lý tin tức

**LLM Prompt**: "Bạn là chuyên gia phân tích BULLISH. Tìm điều kiện quá bán làm cơ hội mua, momentum tích cực đang hình thành, mức hỗ trợ đang giữ, tin tức tích cực làm xúc tác."

**Đầu ra**: `Signal(direction, confidence, reasoning, score)` trong đó score nằm trong khoảng -100 đến +100 (thiên về tích cực)

**Fallback Theo Quy Tắc** (khi LLM timeout hoặc từ chối):
```
RSI < 30:         +30 điểm ("quá bán - vùng mua mạnh")
MACD histogram > 0: +20 điểm ("momentum tích cực")
Price > SMA20 > SMA50: +25 điểm ("xu hướng tăng xác nhận")
Price tại lower BB: +20 điểm ("dự kiến bật")
Volume > 1.5x avg: +10 điểm ("quan tâm mạnh")
Gần hỗ trợ:       +15 điểm ("hỗ trợ giữ")
Tin tức bull:     +20 điểm
```

### Agent 2: Bear Agent

**Thiên kiến**: Bi quan. Chủ động tìm lý do để bán hoặc tránh mua.

**LLM Prompt**: "Bạn là chuyên gia phân tích BEARISH. Tìm điều kiện quá mua làm tín hiệu bán, momentum yếu đi và phân kỳ, mức kháng cự sắp từ chối giá, tin tức tiêu cực làm cảnh báo."

**Fallback Theo Quy Tắc**:
```
RSI > 70:         -30 điểm ("quá mua")
MACD histogram < 0: -20 điểm ("momentum tiêu cực")
Price < SMA20 < SMA50: -25 điểm ("xu hướng giảm")
Price tại upper BB: -20 điểm ("dự kiến bị từ chối")
Volume thấp:      -10 điểm ("rally yếu")
Gần kháng cự:     -15 điểm ("sắp bị từ chối")
Tin tức bear:     -20 điểm
```

### Agent 3: Moderator

**Vai trò**: Cân nhắc lập luận bull vs bear, xem xét đồng thuận/phân kỳ, đưa ra quyết định cuối cùng.

**Logic Quyết Định**:
1. **Trung bình có trọng số**: `combined_score = bull_score * 0.50 + bear_score * 0.50`
2. **Thưởng đồng thuận**: Nếu cả hai agent đồng ý về hướng, cộng +/-15 điểm
3. **Xử lý phân kỳ**: Nếu điểm phân kỳ >60 điểm, theo tín hiệu mạnh hơn với thưởng trọng số 15%
4. **Damping biến động**: Nếu BB width > 5%, giảm điểm 20% (cẩn trọng trong biến động cao)
5. **Khuếch đại tin tức**: Nếu điểm tin tức > 40, cộng 10% điểm tin tức vào combined

**Định Cỡ Vị Thế**:
```
BUY:  position_pct = min(40%, max(5%, combined_score / 2))
SELL: position_pct = min(40%, max(5%, |combined_score| / 2))
HOLD: không hành động
```

### Thực Thi Trong Đấu Trường

Debate chạy mỗi **4 giờ** (có thể cấu hình). Giữa các debate, vị thế được giữ nguyên. Mỗi chu kỳ debate:

1. Lấy 50 nến mới nhất để phân tích kỹ thuật
2. Tính tất cả chỉ báo (RSI, MACD, SMA, BB, volume, hỗ trợ/kháng cự)
3. Đưa vào Bull và Bear agent (LLM với fallback theo quy tắc)
4. Moderator tổng hợp và quyết định
5. Thực thi giao dịch nếu hướng là BUY hoặc SELL với confidence > 5

### Tích Hợp Tin Tức

Mỗi 12 giờ (mỗi 4 debate), tâm lý tin tức được làm mới:
- 7 RSS feed được crawl (CoinTelegraph, CoinDesk, Decrypt, TheBlock, v.v.)
- Tiêu đề được lọc theo từ khóa coin
- Chấm điểm từ bull/bear (-100 đến +100)
- Đưa vào cả hai agent làm ngữ cảnh bổ sung

## Tham Số

| Tham Số | Giá Trị | Mô Tả |
|-----------|-------|-------------|
| `debate_interval` | 4h | Giờ giữa các chu kỳ debate |
| `confidence_threshold` | 5 | Confidence tối thiểu để hành động |
| `max_buy_pct` | 40% | Kích thước vị thế tối đa mỗi lần mua |
| `min_buy_pct` | 5% | Kích thước vị thế tối thiểu mỗi lần mua |
| `news_refresh_interval` | 12h | Giờ giữa các lần cập nhật tâm lý tin tức |

## Mô Hình Phí

Tất cả lệnh đều là **lệnh market**: phí taker 0.10% + slippage 0.02% = 0.12% mỗi giao dịch. Tần suất giao dịch hoàn toàn phụ thuộc vào quyết định LLM -- trong thử nghiệm đấu trường, 12 giao dịch qua 7 ngày (khoảng 1.7 mỗi ngày).

## Điểm Mạnh

1. **Thích ứng với mọi điều kiện thị trường**: Không như các chiến lược theo quy tắc có tham số cố định, các LLM agent có thể suy luận về các tình huống chưa từng có. Khi có tin tức về thay đổi quy định, các agent có thể tính đến ngữ cảnh mà không có chỉ báo cố định nào nắm bắt được.

2. **Góc nhìn cân bằng**: Cấu trúc bull-bear-moderator ngăn thiên kiến góc nhìn đơn. Một LLM đơn có thể nhất quán bullish hoặc bearish; định dạng debate buộc cả hai bên trình bày trường hợp của mình.

3. **Tích hợp nhiều nguồn dữ liệu**: Phân tích kỹ thuật + tâm lý tin tức + suy luận LLM. Không có chiến lược nào khác trong đấu trường kết hợp chỉ báo định lượng với phân tích tin tức định tính.

4. **Quyết định tự ghi lại**: Mỗi giao dịch có một log lập luận đầy đủ (lập luận bull, lập luận bear, quyết định moderator). Điều này vô giá cho phân tích hậu kỳ và cải thiện chiến lược.

5. **Fallback theo quy tắc đảm bảo độ tin cậy**: Khi LLM timeout (xảy ra 3 lần trong thử nghiệm đấu trường), hệ thống theo quy tắc tiếp quản liền mạch. Bot không bao giờ đóng băng chờ một API call.

6. **Cơ chế đồng thuận giảm nhiễu**: Thưởng đồng thuận của moderator (+15 cho đồng ý) và xử lý phân kỳ tạo ra bộ lọc nhiễu tự nhiên. Các đầu ra LLM ngẫu nhiên mâu thuẫn với nhau dẫn đến quyết định HOLD, đó là mặc định đúng.

## Điểm Yếu

1. **Chiến lược thực thi chậm nhất**: Mỗi chu kỳ debate yêu cầu 3 cuộc gọi LLM (bull, bear, moderator). Với timeout 30-45 giây, một chu kỳ debate có thể mất 2-3 phút. Trong đấu trường, điều này làm backtest chậm hơn 10 lần so với các chiến lược thuần quy tắc.

2. **LLM không nhất quán**: Cùng dữ liệu kỹ thuật có thể tạo ra các khuyến nghị khác nhau ở các lệnh gọi khác nhau. LLM không xác định, nên các quyết định của chiến lược có thành phần ngẫu nhiên. Trong một thử nghiệm, bull agent có thể nói "mua" với 70% confidence; chạy lại với dữ liệu giống hệt có thể cho 45% confidence.

3. **ROI tệ nhất trong đấu trường (-0.84%)**: Trong 5 chiến lược chủ động, debate bot hoạt động tệ nhất. Các quyết định LLM không nhất quán vượt trội hơn các chiến lược theo quy tắc đơn giản. ROI -0.84% cho thấy bot đã đưa ra một số quyết định tệ.

4. **Độ trễ cao = bỏ lỡ cơ hội**: Với khoảng debate 4 giờ, bot có thể bỏ lỡ các chuyển động thị trường nhanh. Một flash crash ở giờ 1 sẽ không kích hoạt phản ứng cho đến giờ 4, lúc đó cơ hội có thể đã qua.

5. **Chi phí mỗi quyết định**: Mỗi debate dùng 3 cuộc gọi Claude Haiku ở ~$0.05 mỗi ngân sách. Qua 42 debate (7 ngày), đó là ~$6.30 chi phí LLM -- không tính vào phí giao dịch nhưng là chi phí vận hành thực sự.

6. **Nhạy cảm với prompt engineering**: Chất lượng quyết định giao dịch phụ thuộc lớn vào cách prompt được viết. Một prompt diễn đạt kém có thể dẫn LLM quá thận trọng (luôn HOLD) hoặc quá tích cực (luôn BUY). Các prompt hiện tại hoạt động nhưng chưa được tối ưu.

7. **Tâm lý tin tức thô**: Chấm điểm từ khóa bull/bear đơn giản. "Bitcoin crashes to new low" và "Bitcoin crashes through resistance to new high" đều sẽ chấm là bearish do từ "crashes".

## Điều Kiện Thị Trường Lý Tưởng

- **Tốt nhất**: Thị trường theo tin tức nơi phân tích cơ bản quan trọng (thông báo quy định, phê duyệt ETF, hack lớn). LLM có thể diễn giải ngữ cảnh mà không chỉ báo kỹ thuật nào nắm bắt được.
- **Tốt**: Giai đoạn chuyển tiếp giữa thị trường bull và bear nơi phán đoán giống con người hữu ích
- **Kém**: Thị trường yên ả, kỹ thuật nơi chỉ báo đơn giản (RSI, BB) là đủ
- **Tệ nhất**: Tình huống flash crash (quá chậm để phản ứng) hoặc thị trường có xu hướng mạnh (LLM lưỡng lự giữa bull và bear)

## Kết Quả Đấu Trường (Backtest BTC/USDT 7 ngày)

```
Market: $80,267 -> $78,088 (-2.72%)
Debate:  ROI -0.84%  |  Alpha +1.87%  |  12 trades  |  Cost $3.54
```

Xếp thứ 5 (cuối trong số các chiến lược chủ động). Hãy phân tích timeline:

- **28h**: 7 debate, 0 giao dịch. Tất cả quyết định đều là HOLD -- có thể vì confidence dưới ngưỡng.
- **56h**: 14 debate, giao dịch bắt đầu. ROI +0.34% -- bot mua trong mini rally lên $81,860.
- **84h**: 21 debate, ROI giảm xuống -0.38%. Bot mua gần đỉnh và thị trường đảo chiều.
- **112h**: 28 debate, ROI -0.81%. Thị trường ở $79,361. LLM tiếp tục giữ các vị thế thua.
- **140h**: 35 debate, ROI -0.18%. Một số hồi phục khi thị trường bật lên $80,581.
- **168h (cuối)**: 42 debate, ROI -0.84%. Cú giảm thị trường cuối xuống $78,088 làm tổn hại các vị thế.

Mẫu cho thấy LLM đã đưa ra quyết định thời điểm tệ: mua trong một rally ngắn hóa ra là dead cat bounce.

## Bot Tương Đương

Không có tương đương trực tiếp trong các nền tảng bot crypto hiện có. Các tương tự gần nhất:

| Nền Tảng | Tính Năng | Khác Biệt |
|----------|---------|------------|
| **TradingView** | Tín hiệu cộng đồng | Phân tích viên con người, không phải LLM agent |
| **Dash2Trade** | Tín hiệu AI | Mô hình độc quyền, góc nhìn đơn |
| **Numerai** | Mô hình ensemble | Mô hình ML cộng đồng, không phải định dạng debate |
| **CryptoGPT** | Giao dịch hỗ trợ AI | LLM đơn, không có cấu trúc đối lập |

## Khi Nào Nên Dùng

Dùng chiến lược Debate khi:
- Bạn muốn "ý kiến thứ hai" cùng với các chiến lược theo quy tắc
- Các sự kiện tin tức lớn được kỳ vọng và bạn muốn diễn giải AI
- Bạn chạy nó như một thành viên ensemble (không phải chiến lược duy nhất)
- Bạn đánh giá cao khả năng giải thích (mỗi quyết định có lập luận được ghi lại)

Tránh nó khi:
- Bạn cần thực thi nhanh (khoảng debate 4 giờ quá chậm cho scalping)
- Bạn muốn kết quả xác định, có thể tái tạo
- Chi phí vận hành quan trọng (cuộc gọi LLM cộng dồn)
- Thị trường thuần kỹ thuật (không có xúc tác tin tức)

## Ý Tưởng Tối Ưu Hóa

1. **Mô hình nhanh hơn**: Chuyển từ Haiku sang mô hình nhanh hơn/rẻ hơn cho bull/bear, giữ Haiku chỉ cho moderator
2. **Khoảng cách ngắn hơn**: Chạy debate mỗi 1 giờ thay vì 4 để phản ứng nhanh hơn
3. **Bộ nhớ giữa các debate**: Cho moderator truy cập kết quả debate trước đó -- hiện tại mỗi debate độc lập không có bộ nhớ
4. **Xử lý tin tức tốt hơn**: Dùng LLM để tóm tắt tin tức thay vì chấm điểm từ khóa
5. **Hiệu chuẩn confidence**: Theo dõi độ chính xác của dự đoán trước và cân nhắc quyết định tương lai theo độ chính xác lịch sử
6. **Ensemble với quy tắc**: Dùng quyết định LLM làm bộ điều chỉnh trên tín hiệu theo quy tắc, không phải làm quyết định độc lập
7. **Multi-model debate**: Dùng các mô hình LLM khác nhau cho bull vs bear để tăng đa dạng góc nhìn
