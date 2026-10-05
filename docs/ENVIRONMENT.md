# Environment that works

The versions below are the ones Gage was tested with on 5 October 2026 (the
development laptop). `requirements.txt` gives lower bounds; when something
breaks, pin to these.

## Machine

| | |
|---|---|
| OS | Windows 11 Home 10.0.26200 |
| Python | 3.14.2 (64-bit) |
| GPU | NVIDIA GeForce RTX 3050 6 GB Laptop GPU, driver 591.66 |
| RAM | 11.7 GB (compiling the real MaleCNS graph needs ~3 GB free) |

## Packages

| Package | Version | Notes |
|---|---|---|
| torch | **2.12.0+cu130** | CUDA 13.0 build. The default PyPI wheel is CPU-only. |
| bitsandbytes | 0.50.2 | 4-bit NF4 loading of the fine-tuned model; needs CUDA. |
| transformers | 4.57.3 | |
| peft | 0.21.2 | LoRA adapter |
| accelerate | 1.15.0 | |
| sentence-transformers | 5.1.2 | retrieval embeddings (CPU) |
| flycns | 0.7.0 | FlyBrain LIF simulation |
| numpy | 2.4.0 | |
| fastapi | 0.128.0 | |
| uvicorn | 0.40.0 | |
| sqlalchemy | 2.0.45 | |
| pydantic / pydantic-settings | 2.12.5 / 2.12.0 | |
| openai | 2.48.0 | Groq's OpenAI-compatible API |
| httpx | 0.28.1 | |
| truststore | 0.10.4 | OS certificate store (needed behind Avast HTTPS scanning) |
| bcrypt / PyJWT | 5.0.0 / 2.10.1 | |
| pyarrow / pandas | 23.0.0 / 2.3.3 | only to compile the real MaleCNS graph |
| scikit-learn | 1.7.2 | `requirements-dev.txt` (scripts/eval_flybrain.py); also pulled in by sentence-transformers |

Install the CUDA build of torch **after** `requirements.txt`:

```
python -m pip install -r requirements.txt
python -m pip install torch==2.12.0+cu130 --index-url https://download.pytorch.org/whl/cu130
```

Check it: `python -c "import torch; print(torch.__version__, torch.cuda.is_available())"`
should print `2.12.0+cu130 True`.

On this laptop `pip` on the PATH belongs to a different Python (3.12) than
`python` (3.14). Always use `python -m pip`.

## What needs the GPU, and what does not

| Part | Needs GPU? | Without a GPU |
|---|---|---|
| Live answers (Groq, `LLM_PROVIDER=groq`, the default) | No (remote API) | unchanged |
| Speech (Sarvam STT/TTS) | No (remote API) | unchanged |
| Retrieval embeddings (multilingual-e5-small) | No (runs on CPU) | unchanged |
| FlyBrain, synthetic graph (the default) | No | 0.23 s per reading on CPU |
| FlyBrain, real MaleCNS graph (`FLYBRAIN_GRAPH=malecns`) | Recommended | 10.3-10.6 s per reading on CPU vs 4.3-4.4 s on the RTX 3050; runs in a background thread either way |
| Fine-tuned Sarvam-1 (`LLM_PROVIDER=sarvam_finetuned`, not used live) | Yes in practice | set `SARVAM_DEVICE=cpu` and `SARVAM_QUANTIZATION=none` (4-bit needs CUDA); about 1.6 s per token instead of 0.15 s, so a 256-token answer takes ~7 minutes |

## If the demo machine has no GPU

Nothing to change for the default demo: keep `LLM_PROVIDER=groq`,
`SPEECH_PROVIDER=sarvam` and `FLYBRAIN_GRAPH=synthetic`. Install the plain
`requirements.txt` (it brings the CPU torch wheel) and skip the CUDA step.
The app needs internet for Groq and Sarvam; there is no offline answerer
(the mock provider only returns a canned text, for tests).
