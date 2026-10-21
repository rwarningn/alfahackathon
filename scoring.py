"""Versioned demonstration policy. Not a trained model or bank lending policy."""
import math

POLICY_VERSION = "demo-rules-1.0"


def assess(data):
    rate = 0.24  # Synthetic annual rate, not an Alfa-Bank offer.
    monthly_rate = rate / 12
    amount, months = data["amount"], data["term_months"]
    payment = amount * monthly_rate / (1 - math.pow(1 + monthly_rate, -months))
    free_cash = data["monthly_revenue"] - data["monthly_expenses"]
    total_service = payment + data["existing_payment"]
    coverage = free_cash / total_service
    reasons = []
    if free_cash <= 0:
        reasons.append("Расходы равны выручке или превышают её")
    if coverage < 1:
        reasons.append("Свободного денежного потока недостаточно для платежей")
    if data["business_months"] < 6:
        reasons.append("Бизнес работает менее 6 месяцев")
    if reasons:
        recommendation = "decline"
    elif coverage < 1.3 or data["business_months"] < 12:
        recommendation = "review"
        reasons.append("Нужна ручная проверка: покрытие ниже 1,3 или бизнес моложе года")
    else:
        recommendation = "approve"
        reasons.append("Денежный поток покрывает платежи; бизнес работает не менее года")
    return {"policy_version": POLICY_VERSION, "recommendation": recommendation,
            "reasons": reasons, "monthly_payment": round(payment, 2),
            "coverage": round(coverage, 3), "annual_rate": rate,
            "free_cash": round(free_cash, 2)}
