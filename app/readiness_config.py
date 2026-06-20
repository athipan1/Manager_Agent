import os


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


READINESS_GATE_ENABLED = env_bool("READINESS_GATE_ENABLED", False)
READINESS_GATE_MAX_AGE_SECONDS = int(os.getenv("READINESS_GATE_MAX_AGE_SECONDS", 7 * 24 * 60 * 60))
READINESS_GATE_FAIL_CLOSED = env_bool("READINESS_GATE_FAIL_CLOSED", True)
READINESS_GATE_MIN_FUNDAMENTAL_QUALITY = float(os.getenv("READINESS_GATE_MIN_FUNDAMENTAL_QUALITY", 0.70))
READINESS_GATE_MIN_FUNDAMENTAL_CONFIDENCE = float(os.getenv("READINESS_GATE_MIN_FUNDAMENTAL_CONFIDENCE", 0.35))
READINESS_GATE_TECH_MIN_TRAIN_BARS = int(os.getenv("READINESS_GATE_TECH_MIN_TRAIN_BARS", 180))
READINESS_GATE_TECH_TEST_BARS = int(os.getenv("READINESS_GATE_TECH_TEST_BARS", 30))
READINESS_GATE_TECH_STEP_BARS = int(os.getenv("READINESS_GATE_TECH_STEP_BARS", 30))
