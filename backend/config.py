"""Application configuration loaded from environment / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./storage/observations.db"
    image_dir: str = "./storage/images"

    llm_provider: str = "mock"  # mock | groq | sarvam_finetuned

    # Fine-tuned Sarvam-1 (LLM_PROVIDER=sarvam_finetuned): a LoRA adapter applied
    # with PEFT on top of the base model, loaded once at startup.
    sarvam_base_model: str = "sarvamai/sarvam-1"
    sarvam_adapter_path: str = "./models/sarvam_agri_final"
    sarvam_device: str = "auto"          # auto | cpu | cuda (cuda fails loudly if unavailable)
    # Matches training (QLoRA, 4-bit NF4). 4bit | 8bit | none. Quantization needs CUDA.
    sarvam_quantization: str = "4bit"
    sarvam_max_new_tokens: int = 256

    # Retrieval (RAG) over the curated knowledge base documents.
    knowledge_base_dir: str = "./knowledge_base"
    embedding_model: str = "intfloat/multilingual-e5-small"
    # Cosine floor for a chunk to count as relevant. Measured on this corpus:
    # on-topic questions (English, or translated Kannada) scored >= 0.87, off-topic
    # ones <= 0.81. Below the floor a question retrieves nothing rather than noise.
    retrieval_min_score: float = 0.83
    # Chunks given to the answering model. 4, not 3: the FRP price sits in the
    # 4th chunk for "what is the FRP this season" (measured 2026-10-04).
    retrieval_top_k: int = 4
    # Skip the Sarvam translation and the Groq rewrite when the question as
    # written already retrieves a chunk at this score: English questions scored
    # >= 0.87 on this corpus, Kanglish ones 0.83-0.85 (too low to trust alone).
    retrieval_direct_trigger: float = 0.87
    # Timeout for the small Groq helper calls (query rewrite, grounding check);
    # on timeout the answer goes ahead without them.
    groq_helper_timeout_s: float = 8.0
    # The grounding check reads the top chunks + farm data + answer; it gets
    # longer, and the answer is returned with an 'unavailable' note if it runs out.
    grounding_timeout_s: float = 20.0

    # Groq (OpenAI-compatible). Model is configurable; defaults to GPT-OSS 120B.
    groq_api_key: str = ""
    # Groq namespaces the GPT-OSS models — the id is "openai/gpt-oss-120b", not "gpt-oss-120b".
    groq_model: str = "openai/gpt-oss-120b"
    # Smaller model for the query rewrite and the grounding check. On this
    # account every model has its own tokens-per-minute bucket, so these calls
    # no longer compete with the answer. (No "instant" model is offered here;
    # gpt-oss-20b is the smallest one that returns valid JSON.)
    groq_helper_model: str = "openai/gpt-oss-20b"
    # Groq's tokens-per-minute limit per model on this account (free tier: 8000).
    # Groq counts prompt + max_tokens against it when a request starts.
    groq_tokens_per_minute: int = 8000
    groq_rewrite_max_tokens: int = 160
    groq_check_max_tokens: int = 1200
    # Answer call rate-limited: wait and retry once if Groq says the wait is
    # shorter than this; otherwise fail with 503 and the wait time.
    groq_answer_retry_max_wait_s: float = 20.0

    # Speech (STT + TTS). mock | sarvam. Sarvam handles Kannada/English voice.
    speech_provider: str = "mock"
    sarvam_api_key: str = ""
    sarvam_stt_model: str = "saarika:v2.5"
    sarvam_tts_model: str = "bulbul:v3"  # v2 was deprecated by Sarvam (HTTP 400)
    sarvam_speaker: str = "kavitha"     # must be a bulbul:v3 voice

    # Auth. No usable default: the app refuses to start until JWT_SECRET is set
    # (see require_secure_settings).
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Seed a demo farmer/farm/node with publicly known credentials on startup.
    # Off by default; set SEED_DEMO=true in .env for a local demo only.
    seed_demo: bool = False

    # Key for hashing node API keys (HMAC-SHA256) before they are stored. If
    # unset it is derived from JWT_SECRET; set it explicitly so JWT_SECRET can
    # be rotated without invalidating every device key.
    node_key_secret: str = ""

    # Observation merge: an image and a sensor reading from the same node within
    # this window are merged into one observation.
    merge_window_seconds: int = 60

    # AI farm summary from sensor data: on a new alert, or when the newest summary
    # is older than this. Never per reading (the ESP32 posts every 30 s).
    summary_interval_minutes: int = 60

    # FlyBrain sensor-pattern anomaly detection (services/anomaly.py).
    flybrain_enabled: bool = True
    flybrain_graph: str = "synthetic"          # synthetic | malecns (needs a compiled connectome)
    # Simulation engine: auto (GPU for the real graph when CUDA is present) | numpy | torch.
    flybrain_engine: str = "auto"
    flybrain_raw_dir: str = "./models/malecns/raw"
    flybrain_compiled_dir: str = "./models/malecns/compiled"
    flybrain_sim_steps: int = 1500
    flybrain_baseline_size: int = 40           # normal readings that define the baseline
    flybrain_heldout_size: int = 60            # other normal readings, scored to calibrate
    flybrain_threshold_percentile: float = 99.0
    flybrain_score_interval_minutes: int = 5   # score a farm at most this often
    flybrain_refit_hours: int = 24             # refit each farm's baseline this often
    # Data cleaning: soil moisture exactly 0 for this many consecutive readings
    # (or every channel 0) means a disconnected sensor, not a real field state;
    # those rows are left out of fitting and calibration.
    flybrain_zero_run: int = 3
    flybrain_min_clean_rows: int = 100         # fewer clean rows -> no baseline, no flags

    # A node is considered offline if its last heartbeat is older than this.
    offline_seconds: int = 180
    # How often the server's background timer checks for silent nodes.
    offline_check_seconds: int = 60

    # Alert rule thresholds. ponytail: global constants for V1; make them
    # per-crop / per-farm rows when agronomy demands it.
    humidity_max: float = 85.0       # % -> too humid (disease risk)
    soil_moisture_min: float = 20.0  # % -> too dry (water stress)
    temperature_max: float = 40.0    # C -> heat stress
    low_battery_percent: float = 20.0
    # An open alert auto-resolves only once a newer reading is back inside the
    # safe range by this margin (hysteresis), so a value hovering at a threshold
    # does not raise and resolve a fresh alert on every 30 s reading.
    humidity_clear_margin: float = 3.0      # resolves at <= humidity_max - 3
    soil_moisture_clear_margin: float = 2.0  # resolves at >= soil_moisture_min + 2
    temperature_clear_margin: float = 1.0   # resolves at <= temperature_max - 1
    battery_clear_margin: float = 5.0       # resolves at >= low_battery_percent + 5


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Values that have been published (in this repo's history or docs) and so must
# never sign real tokens: anyone who knows them can forge a login for any farmer.
_KNOWN_PUBLIC_JWT_SECRETS = frozenset({"", "dev-insecure-change-me", "change-me", "secret"})
_MIN_JWT_SECRET_LEN = 32


def require_secure_settings() -> None:
    """Refuse to run with a forgeable JWT secret. Raises RuntimeError, so
    `uvicorn backend.main:app` fails at startup instead of serving insecurely."""
    secret = get_settings().jwt_secret
    if secret in _KNOWN_PUBLIC_JWT_SECRETS or len(secret) < _MIN_JWT_SECRET_LEN:
        raise RuntimeError(
            "JWT_SECRET is missing, a known public default, or shorter than "
            f"{_MIN_JWT_SECRET_LEN} characters. Refusing to start. Generate one with:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
            "and set it as JWT_SECRET in .env or the environment."
        )
