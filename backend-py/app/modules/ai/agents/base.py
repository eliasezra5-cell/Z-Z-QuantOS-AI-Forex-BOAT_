"""Base agent result + shared helpers for the 5-agent pipeline."""

DEFAULT_ABSTENTION = "DATA_INSUFFICIENT"


class AgentResult:
    """Normalized output of one agent in the decision pipeline."""

    def __init__(self, agent_id, name, weight, direction="neutral", confidence=0.0,
                 reasoning="", abstention=DEFAULT_ABSTENTION, data=None,
                 provider_status="", debug=None):
        self.agent_id = agent_id
        self.name = name
        self.weight = weight
        self.direction = direction
        self.confidence = confidence
        self.reasoning = reasoning
        self.abstention = abstention
        self.data = data or {}
        self.provider_status = provider_status
        self.debug = debug or {}

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "weight": self.weight,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "reasoning": self.reasoning,
            "abstention": self.abstention,
            "data": self.data,
            "provider_status": self.provider_status,
            "debug": self.debug,
        }


def clamp01(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
