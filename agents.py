"""Three-agent debate system: Bull, Bear, and Moderator.
Uses Claude CLI as LLM proxy with rule-based fallback."""

from dataclasses import dataclass

from llm_proxy import ask_json


@dataclass
class Signal:
    direction: str       # "BUY", "SELL", "HOLD"
    confidence: float    # 0-100
    reasoning: list[str]
    score: float         # -100 (extreme bear) to +100 (extreme bull)


def _build_ta_summary(ta: dict) -> str:
    lines = []
    lines.append(f"Price: ${ta.get('price', 0):,.2f} ({ta.get('price_change_pct', 0):+.2f}%)")
    if ta.get("rsi_14") is not None:
        lines.append(f"RSI(14): {ta['rsi_14']:.1f}")
    m = ta.get("macd")
    if m:
        lines.append(f"MACD: line {m['macd']:.2f}, signal {m['signal']:.2f}, histogram {m['histogram']:.2f}")
    if ta.get("sma_20"):
        lines.append(f"SMA20: ${ta['sma_20']:,.2f}, SMA50: ${ta.get('sma_50', 0):,.2f}")
    bb = ta.get("bollinger")
    if bb:
        lines.append(f"Bollinger: upper ${bb['upper']:,.2f}, mid ${bb['middle']:,.2f}, lower ${bb['lower']:,.2f}, width {bb['width']:.2f}%")
    vol = ta.get("volume")
    if vol:
        lines.append(f"Volume: {vol['ratio']:.2f}x average")
    sr = ta.get("support_resistance")
    if sr:
        lines.append(f"Support: ${sr['support']:,.2f} ({sr['distance_to_support_pct']:.1f}% away), Resistance: ${sr['resistance']:,.2f} ({sr['distance_to_resistance_pct']:.1f}% away)")
    return "\n".join(lines)


def _build_news_summary(sentiment: dict) -> str:
    lines = [f"Sentiment: {sentiment.get('label', 'N/A')} (score: {sentiment.get('score', 0)})"]
    lines.append(f"Headlines analyzed: {sentiment.get('headline_count', 0)} from {len(sentiment.get('sources', []))} sources")
    for h in sentiment.get("top_headlines", [])[:3]:
        lines.append(f"  - {h[:70]}")
    return "\n".join(lines)


SYSTEM_CONTEXT = (
    "You are analyzing a PAPER TRADING SIMULATOR with fake money for educational purposes. "
    "This is NOT real trading advice. Respond ONLY with a JSON object, no other text."
)


class BullAgent:
    NAME = "BULL"

    def analyze(self, ta: dict, sentiment: dict) -> Signal:
        result = self._llm_analyze(ta, sentiment)
        if result:
            return result
        return self._rule_analyze(ta, sentiment)

    def _llm_analyze(self, ta: dict, sentiment: dict) -> Signal | None:
        prompt = f"""{SYSTEM_CONTEXT}

You are the BULLISH analyst. Your bias is to find reasons to BUY. Look for:
- Oversold conditions as buying opportunities
- Positive momentum forming
- Support levels holding
- Positive news as catalysts
Be optimistic but ground your analysis in the data.

TECHNICAL INDICATORS:
{_build_ta_summary(ta)}

NEWS:
{_build_news_summary(sentiment)}

Respond with JSON: {{"direction":"BUY/SELL/HOLD","confidence":0-100,"reasoning":"your bull case analysis","score":-100 to +100 (positive=bullish)}}"""

        data = ask_json(prompt)
        if not data:
            return None
        try:
            return Signal(
                direction=data.get("direction", "HOLD").upper(),
                confidence=min(100, max(0, float(data.get("confidence", 50)))),
                reasoning=[data.get("reasoning", "LLM analysis")],
                score=max(-100, min(100, float(data.get("score", 0)))),
            )
        except (ValueError, TypeError):
            return None

    def _rule_analyze(self, ta: dict, sentiment: dict) -> Signal:
        score = 0.0
        reasons = []

        rsi = ta.get("rsi_14")
        if rsi is not None:
            if rsi < 30:
                score += 30
                reasons.append(f"RSI {rsi:.0f}: OVERSOLD - strong buy zone")
            elif rsi < 45:
                score += 15
                reasons.append(f"RSI {rsi:.0f}: accumulation zone")
            elif rsi < 60:
                score += 5
                reasons.append(f"RSI {rsi:.0f}: healthy momentum")
            elif rsi > 70:
                score -= 5
                reasons.append(f"RSI {rsi:.0f}: overbought but strong")

        macd_data = ta.get("macd")
        if macd_data:
            if macd_data["histogram"] > 0:
                score += 20
                reasons.append(f"MACD histogram positive ({macd_data['histogram']:.2f})")
            elif macd_data["histogram"] > -0.5:
                score += 10
                reasons.append("MACD about to cross bullish")
            else:
                score -= 5
                reasons.append("MACD bearish but could reverse")

        price = ta.get("price", 0)
        sma20 = ta.get("sma_20")
        sma50 = ta.get("sma_50")
        if sma20 and sma50:
            if price > sma20 > sma50:
                score += 25
                reasons.append("Price > SMA20 > SMA50: uptrend")
            elif price > sma20:
                score += 15
                reasons.append("Price > SMA20: short-term up")
            elif price > sma50:
                score += 5
                reasons.append("Potential bounce off SMA50")
            else:
                score -= 5
                reasons.append("Below both MAs, seeking reversal")

        bb = ta.get("bollinger")
        if bb:
            if price <= bb["lower"]:
                score += 20
                reasons.append("At lower Bollinger: bounce expected")
            elif price < bb["middle"]:
                score += 5
                reasons.append("Below BB mid: room to run up")

        vol = ta.get("volume")
        if vol and vol["ratio"] > 1.5:
            score += 10
            reasons.append(f"Volume {vol['ratio']:.1f}x avg: strong")

        sr = ta.get("support_resistance")
        if sr and sr["distance_to_support_pct"] < 2:
            score += 15
            reasons.append(f"Near support ({sr['distance_to_support_pct']:.1f}%)")

        news_score = sentiment.get("score", 0)
        if news_score > 20:
            score += 20
            reasons.append(f"News BULLISH ({news_score})")
        elif news_score > 0:
            score += 10
            reasons.append(f"News slightly positive ({news_score})")
        elif news_score < -20:
            score -= 5
            reasons.append(f"News bearish ({news_score}) = opportunity")

        score = max(-100, min(100, score))
        confidence = min(100, abs(score))
        direction = "BUY" if score > 20 else "HOLD"

        reasons.append("[fallback: rule-based]")
        return Signal(direction=direction, confidence=confidence, reasoning=reasons, score=score)


class BearAgent:
    NAME = "BEAR"

    def analyze(self, ta: dict, sentiment: dict) -> Signal:
        result = self._llm_analyze(ta, sentiment)
        if result:
            return result
        return self._rule_analyze(ta, sentiment)

    def _llm_analyze(self, ta: dict, sentiment: dict) -> Signal | None:
        prompt = f"""{SYSTEM_CONTEXT}

You are the BEARISH analyst. Your bias is to find reasons to SELL or avoid buying. Look for:
- Overbought conditions as sell signals
- Weakening momentum and divergences
- Resistance levels about to reject price
- Negative news as warning signs
Be cautious and risk-aware in your analysis.

TECHNICAL INDICATORS:
{_build_ta_summary(ta)}

NEWS:
{_build_news_summary(sentiment)}

Respond with JSON: {{"direction":"BUY/SELL/HOLD","confidence":0-100,"reasoning":"your bear case analysis","score":-100 to +100 (negative=bearish)}}"""

        data = ask_json(prompt)
        if not data:
            return None
        try:
            return Signal(
                direction=data.get("direction", "HOLD").upper(),
                confidence=min(100, max(0, float(data.get("confidence", 50)))),
                reasoning=[data.get("reasoning", "LLM analysis")],
                score=max(-100, min(100, float(data.get("score", 0)))),
            )
        except (ValueError, TypeError):
            return None

    def _rule_analyze(self, ta: dict, sentiment: dict) -> Signal:
        score = 0.0
        reasons = []

        rsi = ta.get("rsi_14")
        if rsi is not None:
            if rsi > 70:
                score -= 30
                reasons.append(f"RSI {rsi:.0f}: OVERBOUGHT")
            elif rsi > 60:
                score -= 15
                reasons.append(f"RSI {rsi:.0f}: getting stretched")
            elif rsi > 45:
                score -= 5
                reasons.append(f"RSI {rsi:.0f}: more downside possible")
            elif rsi < 30:
                score += 5
                reasons.append(f"RSI {rsi:.0f}: oversold trap?")

        macd_data = ta.get("macd")
        if macd_data:
            if macd_data["histogram"] < 0:
                score -= 20
                reasons.append(f"MACD histogram negative ({macd_data['histogram']:.2f})")
            elif macd_data["histogram"] < 0.5:
                score -= 10
                reasons.append("MACD weakening")
            else:
                score += 5
                reasons.append("MACD positive but watch divergence")

        price = ta.get("price", 0)
        sma20 = ta.get("sma_20")
        sma50 = ta.get("sma_50")
        if sma20 and sma50:
            if price < sma20 < sma50:
                score -= 25
                reasons.append("Price < SMA20 < SMA50: downtrend")
            elif price < sma20:
                score -= 15
                reasons.append("Price < SMA20: short-term broken")
            elif sma20 < sma50:
                score -= 5
                reasons.append("Death cross warning")
            else:
                score += 5
                reasons.append("Above MAs but overextended?")

        bb = ta.get("bollinger")
        if bb:
            if price >= bb["upper"]:
                score -= 20
                reasons.append("At upper Bollinger: mean reversion expected")
            elif price > bb["middle"]:
                score -= 5
                reasons.append("Above BB mid: could retrace")

        vol = ta.get("volume")
        if vol:
            if vol["ratio"] < 0.7:
                score -= 10
                reasons.append(f"Volume {vol['ratio']:.1f}x: weak rally")
            elif vol["ratio"] > 2.0:
                score -= 5
                reasons.append(f"Volume spike {vol['ratio']:.1f}x: distribution?")

        sr = ta.get("support_resistance")
        if sr and sr["distance_to_resistance_pct"] < 2:
            score -= 15
            reasons.append(f"Near resistance ({sr['distance_to_resistance_pct']:.1f}%)")

        news_score = sentiment.get("score", 0)
        if news_score < -20:
            score -= 20
            reasons.append(f"News BEARISH ({news_score})")
        elif news_score < 0:
            score -= 10
            reasons.append(f"News slightly negative ({news_score})")
        elif news_score > 20:
            score += 5
            reasons.append(f"News positive ({news_score}): sell the news?")

        score = max(-100, min(100, score))
        confidence = min(100, abs(score))
        direction = "SELL" if score < -20 else "HOLD"

        reasons.append("[fallback: rule-based]")
        return Signal(direction=direction, confidence=confidence, reasoning=reasons, score=score)


class ModeratorAgent:
    NAME = "MODERATOR"

    def decide(self, bull_signal: Signal, bear_signal: Signal, ta: dict, sentiment: dict) -> Signal:
        result = self._llm_decide(bull_signal, bear_signal, ta, sentiment)
        if result:
            return result
        return self._rule_decide(bull_signal, bear_signal, ta, sentiment)

    def _llm_decide(self, bull: Signal, bear: Signal, ta: dict, sentiment: dict) -> Signal | None:
        prompt = f"""{SYSTEM_CONTEXT}

You are the MODERATOR. Weigh the Bull vs Bear arguments and make the final call.
Consider risk management, conviction level, and whether both sides agree or disagree.

BULL ANALYSIS (score {bull.score:+.0f}, conf {bull.confidence:.0f}%):
{chr(10).join(bull.reasoning)}

BEAR ANALYSIS (score {bear.score:+.0f}, conf {bear.confidence:.0f}%):
{chr(10).join(bear.reasoning)}

MARKET DATA:
{_build_ta_summary(ta)}

NEWS: {sentiment.get('label', 'N/A')} (score: {sentiment.get('score', 0)})

Weigh both arguments. If they strongly agree, increase conviction. If they diverge heavily, be cautious.
Respond with JSON: {{"direction":"BUY/SELL/HOLD","confidence":0-100,"reasoning":"your moderation analysis","score":-100 to +100}}"""

        data = ask_json(prompt, timeout=45)
        if not data:
            return None
        try:
            reasoning_text = data.get("reasoning", "LLM moderation")
            reasons = [
                f"Bull score: {bull.score:+.0f} (conf: {bull.confidence:.0f}%)",
                f"Bear score: {bear.score:+.0f} (conf: {bear.confidence:.0f}%)",
                f"LLM analysis: {reasoning_text}",
            ]
            return Signal(
                direction=data.get("direction", "HOLD").upper(),
                confidence=min(100, max(0, float(data.get("confidence", 50)))),
                reasoning=reasons,
                score=max(-100, min(100, float(data.get("score", 0)))),
            )
        except (ValueError, TypeError):
            return None

    def _rule_decide(self, bull: Signal, bear: Signal, ta: dict, sentiment: dict) -> Signal:
        reasons = []
        bull_weight = 0.50
        bear_weight = 0.50
        combined_score = bull.score * bull_weight + bear.score * bear_weight

        reasons.append(f"Bull score: {bull.score:+.0f} (conf: {bull.confidence:.0f}%)")
        reasons.append(f"Bear score: {bear.score:+.0f} (conf: {bear.confidence:.0f}%)")
        reasons.append(f"Weighted score: {combined_score:+.1f}")

        if bull.direction == bear.direction:
            reasons.append(f"CONSENSUS: Both say {bull.direction}")
            if bull.direction == "BUY":
                combined_score += 15
            elif bull.direction == "SELL":
                combined_score -= 15

        divergence = abs(bull.score - bear.score)
        if divergence > 60:
            reasons.append(f"HIGH DIVERGENCE ({divergence:.0f}): follow stronger signal")
            if abs(bull.score) > abs(bear.score):
                combined_score += bull.score * 0.15
            else:
                combined_score += bear.score * 0.15
        elif divergence < 20:
            reasons.append(f"LOW DIVERGENCE ({divergence:.0f}): high conviction")

        bb = ta.get("bollinger")
        if bb and bb["width"] > 5:
            reasons.append(f"HIGH VOLATILITY (BB width: {bb['width']:.1f}%): reduce size")
            combined_score *= 0.8

        news_score = sentiment.get("score", 0)
        if abs(news_score) > 40:
            reasons.append(f"STRONG news ({news_score})")
            combined_score += news_score * 0.1

        combined_score = max(-100, min(100, combined_score))

        if combined_score > 10:
            direction = "BUY"
            position_pct = min(40, max(5, combined_score / 2))
            reasons.append(f"DECISION: BUY {position_pct:.0f}%")
        elif combined_score < -10:
            direction = "SELL"
            position_pct = min(40, max(5, abs(combined_score) / 2))
            reasons.append(f"DECISION: SELL {position_pct:.0f}%")
        else:
            direction = "HOLD"
            reasons.append("DECISION: HOLD")

        confidence = min(100, abs(combined_score))
        reasons.append("[fallback: rule-based]")
        return Signal(direction=direction, confidence=confidence, reasoning=reasons, score=combined_score)


def run_debate(ta: dict, sentiment: dict) -> dict:
    bull = BullAgent()
    bear = BearAgent()
    moderator = ModeratorAgent()

    bull_signal = bull.analyze(ta, sentiment)
    bear_signal = bear.analyze(ta, sentiment)
    decision = moderator.decide(bull_signal, bear_signal, ta, sentiment)

    return {
        "bull": bull_signal,
        "bear": bear_signal,
        "decision": decision,
        "summary": {
            "action": decision.direction,
            "confidence": decision.confidence,
            "bull_score": bull_signal.score,
            "bear_score": bear_signal.score,
            "final_score": decision.score,
        },
    }


def format_debate(result: dict, symbol: str, price: float) -> str:
    bull = result["bull"]
    bear = result["bear"]
    decision = result["decision"]

    lines = [
        "",
        "=" * 65,
        f"  AGENT DEBATE: {symbol} @ ${price:,.2f}",
        "=" * 65,
        "",
        f"  {'='*25} BULL AGENT {'='*25}",
        f"  Signal: {bull.direction} | Score: {bull.score:+.0f} | Confidence: {bull.confidence:.0f}%",
    ]
    for r in bull.reasoning:
        lines.append(f"    > {r}")

    lines.extend([
        "",
        f"  {'='*25} BEAR AGENT {'='*25}",
        f"  Signal: {bear.direction} | Score: {bear.score:+.0f} | Confidence: {bear.confidence:.0f}%",
    ])
    for r in bear.reasoning:
        lines.append(f"    > {r}")

    lines.extend([
        "",
        f"  {'='*22} MODERATOR DECISION {'='*22}",
        f"  FINAL: {decision.direction} | Score: {decision.score:+.1f} | Confidence: {decision.confidence:.0f}%",
    ])
    for r in decision.reasoning:
        lines.append(f"    > {r}")

    lines.extend(["", "=" * 65, ""])
    return "\n".join(lines)
