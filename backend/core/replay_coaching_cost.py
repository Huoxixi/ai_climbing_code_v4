"""Public-list-price estimates; no bill, discounts or free quota inferred."""
import math

PRICE_DATE = "2026-09-27"
PRICE_SOURCE = "https://help.aliyun.com/zh/model-studio/model-pricing"


def _count(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return int(value) if math.isfinite(value) and value >= 0 and value.is_integer() else None
    except (TypeError, ValueError, OverflowError):
        return None


def _supported(model):
    return model in {"qwen3-vl-plus", "qwen3-vl-plus-2025-09-23", "qwen3-vl-plus-2025-12-19"} if isinstance(model, str) else False


def _factor(prompt):
    return 1 if prompt <= 32000 else 1.5 if prompt <= 128000 else 3 if prompt <= 256000 else None


def estimate_coaching_cost(provenance):
    result = {"currency": "CNY", "price_date": PRICE_DATE, "source_url": PRICE_SOURCE,
              "basis": "北京地域公开原价；不含姿态处理、免费额度、缓存或活动优惠，实际扣费以百炼账单为准。"}
    if not isinstance(provenance, dict):
        return result | {"status": "unavailable", "reason": "用量记录格式无效。"}
    stages = provenance.get("stage_usage")
    if isinstance(stages, list) and stages:
        amounts = []
        for stage in stages:
            if not isinstance(stage, dict):
                return result | {"status": "unavailable", "reason": "逐次用量记录不完整。"}
            usage = stage.get("usage") or {}
            if not isinstance(usage, dict):
                return result | {"status": "unavailable", "reason": "逐次用量记录不完整。"}
            prompt, output = _count(usage.get("prompt_tokens")), _count(usage.get("completion_tokens"))
            if not _supported(stage.get("model")) or prompt is None or output is None or _factor(prompt) is None:
                return result | {"status": "unavailable", "reason": "模型价格或逐次用量不完整，无法估算。"}
            amounts.append((prompt + output * 10) * _factor(prompt) / 1_000_000)
        amount = round(sum(amounts), 6)
        return result | {"status": "estimated", "amount_min": amount, "amount_max": amount,
                         "request_count": len(stages)}
    usage = provenance.get("usage") or {}
    if not isinstance(usage, dict):
        return result | {"status": "unavailable", "reason": "历史用量记录格式无效。"}
    prompt, output = _count(usage.get("prompt_tokens")), _count(usage.get("completion_tokens"))
    if not _supported(provenance.get("model")) or prompt is None or output is None or _factor(prompt) is None:
        return result | {"status": "unavailable", "reason": "历史报告未记录完整用量或对应模型价格。"}
    # Historic reports only saved the sum. Never apply one tier as an exact bill
    # when the two requests may have occupied different pricing tiers.
    amount = (prompt + output * 10) / 1_000_000
    return result | {"status": "range", "amount_min": round(amount, 6),
                     "amount_max": round(amount * _factor(prompt), 6),
                     "reason": "历史报告只记录总用量，未记录每次请求的价格档位。"}


def budget_policy():
    return {"currency": "CNY", "amount": .20, "max_requests": 3,
            "price_date": PRICE_DATE, "source_url": PRICE_SOURCE,
            "estimate_min": 0, "estimate_max": .20, "kind": "internal_limit",
            "notice": "本次个性化分析按公开价预留不超过 ¥0.20，最多 3 次请求；这是内部预算，非固定收费或供应商精确硬停费。姿态费用另计，优惠未计入；失败、取消或重试也可能收费。"}


def estimate_ledger_cost(ledger):
    """Keep known response charges visible even when another request is unknown."""
    base = {"currency": "CNY", "price_date": PRICE_DATE, "source_url": PRICE_SOURCE,
            "basis": "北京地域公开原价；不含姿态处理、免费额度或优惠，实际扣费以百炼账单为准。"}
    if not isinstance(ledger, list):
        return base | {"status": "unavailable", "usage_complete": False, "reason": "请求记录格式无效，费用可能不完整。"}
    if not ledger:
        return base | {"status": "not_started", "request_count": 0,
                       "reason": "尚未发送付费请求。", "usage_complete": True}
    amounts, unknown = [], 0
    for entry in ledger:
        estimate = estimate_coaching_cost({"stage_usage": [entry]})
        if estimate.get("status") == "estimated" and entry.get("usage_complete") is True:
            amounts.append(estimate["amount_min"])
        else:
            unknown += 1
    known = round(sum(amounts), 6)
    if unknown:
        return base | {"status": "partial" if amounts else "unavailable", "known_amount": known if amounts else None,
                       "known_request_count": len(amounts), "request_count": len(ledger),
                       "unknown_request_count": unknown, "usage_complete": False,
                       "reason": "费用可能不完整；部分请求尚无完整用量，不能确认供应商是否已计费。"}
    return base | {"status": "estimated", "amount_min": known, "amount_max": known,
                   "known_amount": known, "request_count": len(ledger), "usage_complete": True}
