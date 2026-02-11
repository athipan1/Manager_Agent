import os
import json
from typing import Optional
import google.genai as genai
from dotenv import load_dotenv
from .exceptions import ModelError

load_dotenv()

# Configure the Gemini API
model = None
if os.getenv("GEMINI_API_KEY"):
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel('models/gemini-flash-latest')


def get_roe_score(roe):
    """Calculates the score component for ROE."""
    if roe > 0.20:
        return 0.25
    if roe > 0.15:
        return 0.15
    if roe > 0.05:
        return 0.05
    return 0.0


def get_de_ratio_score(de_ratio):
    """Calculates the score component for D/E ratio."""
    if de_ratio < 0.5:
        return 0.20
    if de_ratio < 1.0:
        return 0.10
    if de_ratio < 2.0:
        return 0.05
    return 0.0


def get_revenue_trend_score(historical_revenue: dict) -> tuple[float, str]:
    """
    Analyzes the 3-year revenue trend for growth consistency.
    Returns a score and a descriptive string.
    """
    if not historical_revenue or len(historical_revenue) < 4:
        return 0.0, "ข้อมูลไม่เพียงพอ"

    # Sort by year (descending) to get the last 4 years
    years = sorted(historical_revenue.keys(), reverse=True)[:4]
    revenues = [historical_revenue[year] for year in years]

    # Check growth for the last 3 periods
    growth_years = 0
    if revenues[0] > revenues[1]:
        growth_years += 1
    if revenues[1] > revenues[2]:
        growth_years += 1
    if revenues[2] > revenues[3]:
        growth_years += 1

    if growth_years == 3:
        score = 0.15
        trend_string = "เติบโตต่อเนื่อง 3 ปี"
    elif growth_years == 2:
        score = 0.10
        trend_string = "เติบโต 2 ใน 3 ปีล่าสุด"
    elif growth_years == 1:
        score = 0.05
        trend_string = "เติบโต 1 ใน 3 ปีล่าสุด"
    else:
        score = 0.0
        trend_string = "รายได้ไม่เติบโต"

    return score, trend_string


def calculate_cagr(historical_revenue: dict) -> Optional[float]:
    """Calculates the 3-year Compound Annual Growth Rate (CAGR)."""
    if not historical_revenue or len(historical_revenue) < 4:
        return None

    years = sorted(historical_revenue.keys(), reverse=True)[:4]
    start_value = historical_revenue[years[3]]  # Earliest year
    end_value = historical_revenue[years[0]]   # Most recent year

    if start_value is None or end_value is None or start_value <= 0:
        return None

    try:
        cagr = ((end_value / start_value) ** (1/3)) - 1
        return cagr
    except (TypeError, ZeroDivisionError):
        return None


def get_margins_score(margins):
    """Calculates the score component for profit margins."""
    if margins > 0.20:
        return 0.10
    return 0.0


def get_pe_ratio_score(pe_ratio):
    """Calculates the score component for P/E ratio."""
    if pe_ratio is None:
        return 0.0
    if 0 < pe_ratio < 15:
        return 0.10
    if pe_ratio < 25:
        return 0.05
    return 0.0


def get_dividend_yield_score(dividend_yield):
    """Calculates the score component for dividend yield."""
    if dividend_yield is None:
        return 0.0
    if dividend_yield > 0.04:
        return 0.10
    if dividend_yield > 0.02:
        return 0.05
    return 0.0


def get_pb_ratio_score(pb_ratio):
    """Calculates the score component for P/B ratio."""
    if pb_ratio is None:
        return 0.0
    if 0 < pb_ratio < 1.2:
        return 0.05
    return 0.0


def get_eps_score(eps):
    """Calculates the score component for EPS."""
    if eps is None:
        return 0.0
    if eps > 0:
        return 0.05
    return 0.0


def get_growth_score(growth_rate):
    """Gives a significant score for high growth rates (for Revenue and EPS)."""
    if growth_rate is None:
        return 0.0
    if growth_rate > 0.25:
        return 0.20  # High score for strong growth
    if growth_rate > 0.10:
        return 0.10
    if growth_rate > 0:
        return 0.05
    return 0.0


def get_forward_pe_score(forward_pe):
    """Scores based on the forward P/E ratio."""
    if forward_pe is None:
        return 0.0
    if 0 < forward_pe < 15:
        return 0.10
    if forward_pe < 25:
        return 0.05
    return 0.0


def get_peg_ratio_score(peg_ratio):
    """Scores based on the PEG ratio. Lower is better."""
    if peg_ratio is None:
        return 0.0
    if 0 < peg_ratio < 1.0:
        return 0.10  # Very favorable
    if peg_ratio < 1.5:
        return 0.05
    return 0.0


def get_cash_flow_score(cash_flow):
    """Scores based on operating cash flow. Positive is good."""
    if cash_flow is None:
        return 0.0
    if cash_flow > 0:
        return 0.10  # Positive cash flow is crucial
    return 0.0


def calculate_growth_score(data: dict, trend_score: float) -> dict:
    """
    Calculates a score based on Growth Investing principles.
    Returns a dictionary with the total score and a breakdown.
    """
    scores = {
        "growth": 0.0, "valuation": 0.0, "quality": 0.0, "total": 0.0
    }
    try:
        # --- Factors ---
        roe = data.get("ROE") or 0.0
        de_ratio = (data.get("Debt to Equity Ratio") or float('inf')) / 100.0
        margins = data.get("Profit Margins") or 0.0
        pe_ratio = data.get("P/E Ratio")
        pb_ratio = data.get("P/B Ratio")
        eps = data.get("EPS")
        revenue_growth = data.get("Revenue Growth")
        eps_growth = data.get("EPS Growth")
        forward_pe = data.get("Forward P/E")
        peg_ratio = data.get("PEG Ratio")
        cash_flow = data.get("Operating Cash Flow")
        dividend_yield = data.get("Dividend Yield")

        # --- Scoring ---
        # Growth Factors (High Weight)
        scores["growth"] += get_growth_score(revenue_growth)
        scores["growth"] += get_growth_score(eps_growth)
        scores["growth"] += trend_score

        # Valuation Factors
        scores["valuation"] += get_peg_ratio_score(peg_ratio)
        scores["valuation"] += get_forward_pe_score(forward_pe)
        scores["valuation"] += get_pe_ratio_score(pe_ratio)
        scores["valuation"] += get_pb_ratio_score(pb_ratio)

        # Quality & Stability Factors
        scores["quality"] += get_roe_score(roe)
        scores["quality"] += get_de_ratio_score(de_ratio)
        scores["quality"] += get_margins_score(margins)
        scores["quality"] += get_cash_flow_score(cash_flow)
        scores["quality"] += get_eps_score(eps)
        # Lower weight for dividends in a growth model
        scores["quality"] += get_dividend_yield_score(dividend_yield) * 0.5

        scores["total"] = sum(scores.values())
    except (ValueError, TypeError):
        return {k: 0.0 for k in scores}
    # Normalize and round
    for key in scores:
        scores[key] = round(scores[key], 2)
    scores["total"] = min(round(scores["total"], 2), 1.0)
    return scores


def calculate_value_score(data: dict) -> dict:
    """
    Calculates a score based on Value Investing principles.
    Returns a dictionary with the total score and a breakdown.
    """
    scores = {
        "valuation": 0.0, "quality": 0.0, "financial_health": 0.0, "total": 0.0
    }
    try:
        # --- Factors ---
        roe = data.get("ROE") or 0.0
        de_ratio = (data.get("Debt to Equity Ratio") or float('inf')) / 100.0
        margins = data.get("Profit Margins") or 0.0
        pe_ratio = data.get("P/E Ratio")
        pb_ratio = data.get("P/B Ratio")
        eps = data.get("EPS")
        cash_flow = data.get("Operating Cash Flow")
        dividend_yield = data.get("Dividend Yield")

        # --- Scoring ---
        # Valuation Factors (High Weight)
        scores["valuation"] += get_pe_ratio_score(pe_ratio) * 3.0
        scores["valuation"] += get_pb_ratio_score(pb_ratio) * 3.0

        # Financial Health (High Weight)
        scores["financial_health"] += get_de_ratio_score(de_ratio) * 2.0  # High weight

        # Quality & Stability Factors
        scores["quality"] += get_roe_score(roe)
        scores["quality"] += get_margins_score(margins)
        scores["quality"] += get_cash_flow_score(cash_flow)
        scores["quality"] += get_eps_score(eps)
        scores["quality"] += get_dividend_yield_score(dividend_yield)

        scores["total"] = sum(scores.values())
    except (ValueError, TypeError):
        return {k: 0.0 for k in scores}

    # Normalize and round
    for key in scores:
        scores[key] = round(scores[key], 2)
    scores["total"] = min(round(scores["total"], 2), 1.0)
    return scores


def get_dividend_sustainability_score(dividend_history: dict) -> tuple[float, str]:
    """
    Analyzes the dividend history for consistency and growth.
    """
    if not dividend_history or len(dividend_history) < 4:
        return 0.0, "ข้อมูลปันผลไม่เพียงพอ"

    years = sorted(dividend_history.keys(), reverse=True)[:5]
    dividends = [dividend_history[year] for year in years]

    growth_years = 0
    stable_years = 0

    for i in range(len(dividends) - 1):
        if dividends[i] > dividends[i+1]:
            growth_years += 1
            stable_years += 1
        elif dividends[i] == dividends[i+1] and dividends[i] > 0:
            stable_years += 1

    if growth_years >= 3:
        score = 0.25
        sustainability = "ปันผลเติบโตต่อเนื่อง"
    elif stable_years >= 4:
        score = 0.20
        sustainability = "ปันผลสม่ำเสมอ"
    elif stable_years >= 2:
        score = 0.10
        sustainability = "ปันผลค่อนข้างคงที่"
    else:
        score = 0.0
        sustainability = "ปันผลไม่สม่ำเสมอ"

    return score, sustainability


def calculate_dividend_score(data: dict) -> dict:
    """
    Calculates a score based on Dividend Investing principles.
    Returns a dictionary with the total score and a breakdown.
    """
    scores = {
        "yield": 0.0, "sustainability": 0.0, "quality": 0.0, "total": 0.0
    }
    try:
        # --- Factors ---
        dividend_yield = data.get("Dividend Yield") or 0.0
        dividend_history = data.get("Dividend History", {})
        de_ratio = (data.get("Debt to Equity Ratio") or float('inf')) / 100.0
        cash_flow = data.get("Operating Cash Flow")
        roe = data.get("ROE") or 0.0

        # --- Scoring ---
        # Yield (High Weight)
        scores["yield"] += get_dividend_yield_score(dividend_yield) * 2.0  # Double weight

        # Sustainability (High Weight)
        sustainability_score, _ = get_dividend_sustainability_score(dividend_history)
        scores["sustainability"] += sustainability_score

        # Quality & Financial Health
        scores["quality"] += get_de_ratio_score(de_ratio)
        scores["quality"] += get_cash_flow_score(cash_flow)
        scores["quality"] += get_roe_score(roe)

        scores["total"] = sum(scores.values())
    except (ValueError, TypeError):
        return {k: 0.0 for k in scores}

    # Normalize and round
    for key in scores:
        scores[key] = round(scores[key], 2)
    scores["total"] = min(round(scores["total"], 2), 1.0)
    return scores


def generate_actionable_strength(score: float) -> str:
    """Generates an actionable strength signal based on the calculated score."""
    if score >= 0.8:
        return "strong_buy"
    if score >= 0.6:
        return "buy"
    if score >= 0.4:
        return "neutral"
    if score >= 0.2:
        return "sell"
    return "strong_sell"


def create_growth_prompt(
    data: dict, ticker: str, trend: str, cagr: Optional[float]
) -> str:
    """Creates a Chain-of-Thought prompt for the 'Growth' style."""
    # Helper for safe formatting
    def format_value(value, format_spec):
        return f"{value:{format_spec}}" if isinstance(value, (int, float)) else "N/A"

    formatted_data = {
        # Growth
        "Revenue Growth (YoY)": format_value(data.get('Revenue Growth'), '.2%'),
        "EPS Growth (YoY)": format_value(data.get('EPS Growth'), '.2%'),
        "3-Year Revenue Trend": trend,
        "3-Year Revenue CAGR": format_value(cagr, '.2%'),
        "Operating Cash Flow": f"${data.get('Operating Cash Flow', 0):,.0f}",

        # Valuation
        "Forward P/E Ratio": format_value(data.get('Forward P/E'), '.2f'),
        "PEG Ratio": format_value(data.get('PEG Ratio'), '.2f'),
        "P/E Ratio": format_value(data.get('P/E Ratio'), '.2f'),
        "P/B Ratio": format_value(data.get('P/B Ratio'), '.2f'),

        # Quality & Health
        "Return on Equity (ROE)": format_value(data.get('ROE'), '.2%'),
        "Debt to Equity Ratio": format_value(data.get('Debt to Equity Ratio'), '.2f'),
        "Profit Margins": format_value(data.get('Profit Margins'), '.2%'),
        "Earnings Per Share (EPS)": format_value(data.get('EPS'), '.2f'),
        "Dividend Yield": format_value(data.get('Dividend Yield'), '.2%'),
    }

    data_string = "\n".join([f"- {key}: {value}" for key, value in formatted_data.items()])
    prompt = (
        f"คุณคือผู้เชี่ยวชาญด้านการวิเคราะห์หุ้นเติบโต (Growth Investing)\n"
        f"**คำสั่ง:** วิเคราะห์ข้อมูลทางการเงินของบริษัท {ticker} และสรุปภาพรวมในรูปแบบย่อหน้าเดียวที่คมชัดและลึกซึ้ง\n"
        f"**ข้อมูลที่มี:**\n{data_string}\n\n"
        f"**กฎเหล็ก (Guardrails):**\n"
        f"1.  **ห้าม** สร้างข้อมูลหรือตัวเลขใดๆ ที่ไม่มีอยู่ใน `ข้อมูลที่มี` โดยเด็ดขาด\n"
        f"2.  วิเคราะห์จากข้อมูลที่ให้มาเท่านั้น\n"
        f"3.  หากข้อมูลบางอย่างเป็น 'N/A' ให้ระบุว่า \"ข้อมูลไม่เพียงพอที่จะประเมิน\" ในส่วนนั้นๆ\n"
        f"4.  คำตอบทั้งหมดต้องเป็นภาษาไทย\n\n"
        f"**กระบวนการคิด (Chain of Thought) สำหรับหุ้นเติบโต:**\n"
        f"1.  **ประเมินศักยภาพการเติบโต (Growth Potential):** นี่คือส่วนสำคัญที่สุด "
        f"ดูที่ Revenue Growth และ EPS Growth เป็นหลัก ว่าเติบโตสูงและน่าประทับใจหรือไม่ "
        f"ใช้ 3-Year Trend และ CAGR เพื่อดูความสม่ำเสมอของการเติบโตในอดีต\n"
        f"2.  **ประเมินมูลค่าเทียบกับการเติบโต (Valuation vs. Growth):** หุ้นเติบโตมักมี P/E สูง "
        f"ดังนั้นให้ดูที่ Forward P/E เพื่อประเมินมูลค่าในอนาคต และใช้ PEG Ratio เพื่อตัดสินว่า P/E "
        f"สูงนั้นสมเหตุสมผลหรือไม่ (ค่า PEG ต่ำกว่า 1.5 ถือว่าดี)\n"
        f"3.  **ประเมินคุณภาพและเสถียรภาพ (Quality & Stability):** บริษัทเติบโตต้องมีพื้นฐานที่ดีด้วย "
        f"ดูที่ ROE และ Profit Margins เพื่อวัดความสามารถในการทำกำไร, "
        f"Operating Cash Flow เพื่อดูสภาพคล่องที่แท้จริง, และ Debt to Equity "
        f"เพื่อดูภาระหนี้สิน\n"
        f"4.  **สรุปภาพรวม:** สังเคราะห์ข้อมูลทั้งหมดเพื่อสร้างบทสรุปที่กระชับ "
        f"โดยเน้นที่ \"โอกาสในการเติบโต\" เทียบกับ \"ความเสี่ยงและมูลค่าปัจจุบัน\"\n\n"
        f"**ผลลัพธ์ที่ต้องการ:**\nเขียนบทวิเคราะห์สรุป (ย่อหน้าเดียว) ตามกระบวนการคิดข้างต้น"
    )
    return prompt


def create_value_prompt(data: dict, ticker: str) -> str:
    """Creates a Chain-of-Thought prompt for the 'Value' style."""
    def format_value(value, format_spec):
        return f"{value:{format_spec}}" if isinstance(value, (int, float)) else "N/A"

    formatted_data = {
        # Valuation
        "P/E Ratio": format_value(data.get('P/E Ratio'), '.2f'),
        "P/B Ratio": format_value(data.get('P/B Ratio'), '.2f'),

        # Quality & Health
        "Debt to Equity Ratio": format_value(data.get('Debt to Equity Ratio'), '.2f'),
        "Return on Equity (ROE)": format_value(data.get('ROE'), '.2%'),
        "Profit Margins": format_value(data.get('Profit Margins'), '.2%'),
        "Operating Cash Flow": f"${data.get('Operating Cash Flow', 0):,.0f}",
        "Dividend Yield": format_value(data.get('Dividend Yield'), '.2%'),
    }

    data_string = "\n".join([f"- {key}: {value}" for key, value in formatted_data.items()])
    prompt = (
        f"คุณคือผู้เชี่ยวชาญด้านการวิเคราะห์หุ้นคุณค่า (Value Investing)\n"
        f"**คำสั่ง:** วิเคราะห์ข้อมูลทางการเงินของบริษัท {ticker} "
        f"เพื่อค้นหา 'Margin of Safety' และสรุปภาพรวม\n"
        f"**ข้อมูลที่มี:**\n{data_string}\n\n"
        f"**กฎเหล็ก (Guardrails):**\n"
        f"1. **ห้าม** สร้างข้อมูลใดๆ ที่ไม่มีอยู่โดยเด็ดขาด\n"
        f"2. วิเคราะห์จากข้อมูลที่ให้มาเท่านั้น\n"
        f"3. หากข้อมูลเป็น 'N/A' ให้ระบุว่า \"ข้อมูลไม่เพียงพอที่จะประเมิน\"\n"
        f"4. คำตอบทั้งหมดต้องเป็นภาษาไทย\n\n"
        f"**กระบวนการคิด (Chain of Thought) สำหรับหุ้นคุณค่า:**\n"
        f"1. **ประเมินมูลค่า (Valuation):** นี่คือส่วนสำคัญที่สุด ดูที่ P/E และ P/B Ratio เป็นหลัก "
        f"ค่าเหล่านี้ต่ำหรือไม่เมื่อเทียบกับค่าเฉลี่ยในอดีตหรือคู่แข่ง "
        f"(แม้จะไม่มีข้อมูลคู่แข่ง ให้พิจารณาจากหลักการทั่วไปว่าค่ายิ่งต่ำยิ่งดี)\n"
        f"2. **ประเมินความแข็งแกร่งของกิจการ (Business Strength):** บริษัทที่ดีต้องมีพื้นฐานแข็งแกร่ง "
        f"ดูที่ ROE และ Profit Margins เพื่อวัดความสามารถในการทำกำไร และ Operating Cash Flow เพื่อดูสภาพคล่อง\n"
        f"3. **ประเมินความเสี่ยงทางการเงิน (Financial Risk):** หุ้นคุณค่าที่ดีไม่ควรมีความเสี่ยงสูง "
        f"ดูที่ Debt to Equity Ratio ว่าอยู่ในระดับที่จัดการได้หรือไม่ (โดยทั่วไปควรต่ำกว่า 2)\n"
        f"4. **สรุปภาพรวมและ Margin of Safety:** สังเคราะห์ข้อมูลทั้งหมดเพื่อสรุปว่าบริษัทมีพื้นฐานที่ดี"
        f"ในราคาที่เหมาะสมหรือไม่ กล่าวคือ มี 'ส่วนเผื่อเพื่อความปลอดภัย' (Margin of Safety) หรือไม่\n\n"
        f"**ผลลัพธ์ที่ต้องการ:**\nเขียนบทวิเคราะห์สรุป (ย่อหน้าเดียว) ตามกระบวนการคิดข้างต้น"
    )
    return prompt


def create_dividend_prompt(data: dict, ticker: str, sustainability: str) -> str:
    """Creates a Chain-of-Thought prompt for the 'Dividend' style."""
    def format_value(value, format_spec):
        return f"{value:{format_spec}}" if isinstance(value, (int, float)) else "N/A"

    formatted_data = {
        "Dividend Yield": format_value(data.get('Dividend Yield'), '.2%'),
        "Dividend Sustainability": sustainability,
        "Debt to Equity Ratio": format_value(data.get('Debt to Equity Ratio'), '.2f'),
        "Operating Cash Flow": f"${data.get('Operating Cash Flow', 0):,.0f}",
        "Return on Equity (ROE)": format_value(data.get('ROE'), '.2%'),
    }

    data_string = "\n".join([f"- {key}: {value}" for key, value in formatted_data.items()])
    prompt = (
        f"คุณคือผู้เชี่ยวชาญด้านการวิเคราะห์หุ้นปันผล (Dividend Investing)\n"
        f"**คำสั่ง:** วิเคราะห์ข้อมูลทางการเงินของบริษัท {ticker} "
        f"เพื่อประเมินความน่าสนใจและความยั่งยืนของเงินปันผล\n"
        f"**ข้อมูลที่มี:**\n{data_string}\n\n"
        f"**กฎเหล็ก (Guardrails):**\n"
        f"1. **ห้าม** สร้างข้อมูลใดๆ ที่ไม่มีอยู่โดยเด็ดขาด\n"
        f"2. วิเคราะห์จากข้อมูลที่ให้มาเท่านั้น\n"
        f"3. คำตอบทั้งหมดต้องเป็นภาษาไทย\n\n"
        f"**กระบวนการคิด (Chain of Thought) สำหรับหุ้นปันผล:**\n"
        f"1. **ประเมินผลตอบแทน (Yield):** นี่คือส่วนสำคัญที่สุด "
        f"ดูที่ Dividend Yield ว่าสูงน่าดึงดูดใจหรือไม่ (โดยทั่วไปสูงกว่า 3-4% ถือว่าดี)\n"
        f"2. **ประเมินความยั่งยืน (Sustainability):** ปันผลสูงแต่ไม่ยั่งยืนก็ไม่มีประโยชน์ "
        f"ดูที่ Dividend Sustainability เพื่อประเมินความสม่ำเสมอในอดีต และดูที่ Operating Cash Flow "
        f"กับ Debt to Equity Ratio เพื่อประเมินว่าบริษัทมีสถานะทางการเงินแข็งแกร่งพอที่จะจ่ายปันผลต่อไปในอนาคตหรือไม่\n"
        f"3. **ประเมินคุณภาพของกิจการ (Business Quality):** บริษัทที่จ่ายปันผลได้ดีควรเป็นกิจการที่ดีด้วย "
        f"ดูที่ ROE เพื่อวัดความสามารถในการทำกำไร\n"
        f"4. **สรุปภาพรวม:** สังเคราะห์ข้อมูลเพื่อสรุปว่าหุ้นตัวนี้เป็นหุ้นปันผลที่น่าลงทุนหรือไม่ "
        f"โดยพิจารณาทั้งผลตอบแทนและความเสี่ยง\n\n"
        f"**ผลลัพธ์ที่ต้องการ:**\nเขียนบทวิเคราะห์สรุป (ย่อหน้าเดียว) ตามกระบวนการคิดข้างต้น"
    )
    return prompt


def analyze_financials(ticker: str, data: dict, style: str = "growth") -> dict:
    """
    Uses Python for scoring and JSON assembly, and an LLM for reasoning.
    """
    if not data:
        return None

    # --- Data Preparation ---
    historical_revenue = data.get("Historical Revenue", {})
    trend_score, trend_string = get_revenue_trend_score(historical_revenue)
    cagr = calculate_cagr(historical_revenue)
    dividend_history = data.get("Dividend History", {})
    _, sustainability_string = get_dividend_sustainability_score(dividend_history)

    # --- Scoring & Prompt Generation based on Style ---
    if style == "growth":
        score_details = calculate_growth_score(data, trend_score)
        prompt = create_growth_prompt(data, ticker, trend_string, cagr)
    elif style == "value":
        score_details = calculate_value_score(data)
        prompt = create_value_prompt(data, ticker)
    elif style == "dividend":
        score_details = calculate_dividend_score(data)
        prompt = create_dividend_prompt(data, ticker, sustainability_string)
    else:
        raise ValueError(f"Invalid analysis style: {style}")

    score = score_details.get("total", 0.0)
    strength = generate_actionable_strength(score)

    reasoning = "ไม่สามารถสร้างคำวิเคราะห์ได้"  # Default value
    # Skip LLM call if API key is not set (for testing)
    if os.getenv("GEMINI_API_KEY"):
        try:
            response = model.generate_content(prompt)
            generated_text = response.text.strip()
            if generated_text:
                reasoning = generated_text
        except Exception as e:
            print(f"An error occurred during text generation: {e}")
            raise ModelError(f"Failed to generate analysis from the model: {e}")

    return {
        "strength": strength,
        "reasoning": reasoning,
        "score": score,
        "score_details": score_details,
        "key_metrics": data,
        "analysis_source": "llm"  # Indicate the source of the analysis
    }


if __name__ == '__main__':
    sample_ticker = 'AAPL'
    sample_data = {
        'ROE': 1.7142, 'Debt to Equity Ratio': 152.41,
        'Quarterly Revenue Growth (yoy)': 0.079, 'Profit Margins': 0.2692
    }
    print(f"--- Starting analysis for {sample_ticker} ---")
    analysis_result = analyze_financials(sample_ticker, sample_data)
    if analysis_result:
        print("\n--- Analysis Result ---")
        print(json.dumps(analysis_result, indent=4, ensure_ascii=False))
