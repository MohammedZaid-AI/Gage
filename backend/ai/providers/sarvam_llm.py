"""Gage's fine-tuned Sarvam-1: a LoRA adapter on top of sarvamai/sarvam-1.

Selected with LLM_PROVIDER=sarvam_finetuned. The adapter (SARVAM_ADAPTER_PATH,
default models/sarvam_agri_final) is loaded with PEFT's PeftModel.from_pretrained
over the base model — never as a standalone model. Loading happens once, when
the provider is constructed by the first chat request that asks for this engine
(ai/service.get_llm; never at server startup); later requests only run generation.

The prompt reproduces the training format from Gage_Sarvam_Finetune_Colab.ipynb
exactly (### System / ### Context / ### Farmer / ### Assistant); measured on the
real adapter, it scores lower loss than the tokenizer's [INST] chat template. The
model was trained with max_length=1024 on (knowledge, question, answer) rows, so
it receives the compact prompt: retrieved knowledge in ### Context and the
farmer's own question in ### Farmer. No farm sensor readings are sent to it.

Generation is CPU/GPU-bound and blocking; callers must run it off the event
loop (the routers do, via a threadpool). A lock serialises generations so
concurrent requests queue instead of competing for the same weights.
"""
import logging
import threading
import time
from pathlib import Path

from backend.ai.base import LLMError, LLMProvider
from backend.config import get_settings

logger = logging.getLogger("gage.ai.sarvam_llm")

# Verbatim from the training notebook (Cell 5).
# The exact training system string (Gage_Sarvam_Finetune_Colab.ipynb, Cell 5).
# This model mirrors the FARMER turn's language: a Kanglish question gives a
# Kanglish answer, an English question an English answer. Instructions to always
# use Kanglish (in this System turn or appended to the Farmer turn) do NOT hold
# reliably -- tested 2026-10-05, it kept answering English questions in English
# (test_runs/kanglish_steer.txt). To keep the demo in Kanglish, ask in Kanglish
# (the suggestion chips are Kanglish).
SYSTEM_PROMPT = ("You are Gage, an AI assistant that provides accurate, "
                 "practical agricultural advice in Kannada-English.")


def build_prompt(question: str, context: str) -> str:
    """The exact training template, ending where the model must continue."""
    return (f"### System\n{SYSTEM_PROMPT}\n\n"
            f"### Context\n{context}\n\n"
            f"### Farmer\n{question}\n\n"
            f"### Assistant\n")


def _resolve_base(model_id: str) -> str:
    """Use the local snapshot when present so startup needs no network."""
    if Path(model_id).is_dir():
        return model_id
    from huggingface_hub import snapshot_download

    try:
        return snapshot_download(model_id, local_files_only=True)
    except Exception:
        return model_id


class SarvamFinetunedLLMProvider(LLMProvider):
    prompt_style = "compact"

    def __init__(self) -> None:
        s = get_settings()
        adapter = Path(s.sarvam_adapter_path)
        if not (adapter / "adapter_config.json").is_file():
            raise FileNotFoundError(
                f"LoRA adapter not found at {adapter.resolve()} (expected adapter_config.json "
                "+ adapter weights). Copy the trained adapter there or set SARVAM_ADAPTER_PATH."
            )

        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        cuda = torch.cuda.is_available()
        device = s.sarvam_device
        if device == "auto":
            device = "cuda" if cuda else "cpu"
        if device == "cuda" and not cuda:
            raise RuntimeError(
                f"SARVAM_DEVICE=cuda but torch {torch.__version__} has no CUDA "
                f"(built with CUDA {torch.version.cuda}). Install a CUDA build of torch."
            )
        if device == "cpu":
            logger.warning("Sarvam-1 is loading on CPU (torch %s, cuda available=%s): generation "
                           "will take seconds per token", torch.__version__, cuda)
        # Sarvam-1's weights are native bfloat16 (the notebook trained in bf16).
        dtype = torch.bfloat16
        quant = s.sarvam_quantization.lower()

        t0 = time.perf_counter()
        base_path = _resolve_base(s.sarvam_base_model)
        self._tokenizer = AutoTokenizer.from_pretrained(base_path)
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token
        if device == "cuda":
            # Same quantization the adapter was trained against (notebook Cell 6):
            # 4-bit NF4, double quant, bf16 compute, everything on GPU 0.
            qconfig = None
            if quant == "4bit":
                from transformers import BitsAndBytesConfig

                qconfig = BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
                )
            elif quant == "8bit":
                from transformers import BitsAndBytesConfig

                qconfig = BitsAndBytesConfig(load_in_8bit=True)
            base = AutoModelForCausalLM.from_pretrained(
                base_path, dtype=dtype, quantization_config=qconfig, device_map={"": 0},
            )
        else:
            if quant != "none":
                logger.warning("SARVAM_QUANTIZATION=%s needs CUDA (bitsandbytes); loading bf16", quant)
                quant = "none"
            base = AutoModelForCausalLM.from_pretrained(base_path, dtype=dtype, low_cpu_mem_usage=True)
        self._model = PeftModel.from_pretrained(base, str(adapter)).eval()
        self._device = "cuda:0" if device == "cuda" else "cpu"
        self._torch = torch
        self._max_new_tokens = s.sarvam_max_new_tokens
        self._lock = threading.Lock()
        gpu = (f"{torch.cuda.get_device_name(0)}, {torch.cuda.memory_allocated(0) / 2**30:.2f} GiB "
               f"allocated of {torch.cuda.get_device_properties(0).total_memory / 2**30:.2f} GiB"
               if device == "cuda" else "none")
        logger.info("fine-tuned Sarvam-1 loaded: base=%s adapter=%s device=%s quantization=%s "
                    "torch=%s cuda_available=%s gpu=[%s] in %.1fs",
                    s.sarvam_base_model, adapter, self._device, quant, torch.__version__, cuda,
                    gpu, time.perf_counter() - t0)

    def answer(self, question: str, context: str, language: str) -> str:
        # `language` is not passed to the model: it was trained to answer in the
        # farmer's own register, and the prompt carries the farmer's words.
        prompt = build_prompt(question, context)
        try:
            inputs = self._tokenizer(prompt, return_tensors="pt").to(self._device)
            t0 = time.perf_counter()
            with self._lock, self._torch.inference_mode():
                out = self._model.generate(
                    **inputs,
                    max_new_tokens=self._max_new_tokens,
                    do_sample=False,                 # deterministic advice
                    repetition_penalty=1.1,
                    pad_token_id=self._tokenizer.pad_token_id,
                    eos_token_id=self._tokenizer.eos_token_id,
                )
            new_tokens = out[0, inputs["input_ids"].shape[1]:]
            text = self._tokenizer.decode(new_tokens, skip_special_tokens=True)
            logger.info("generated %d tokens in %.1fs (prompt %d tokens)",
                        len(new_tokens), time.perf_counter() - t0, inputs["input_ids"].shape[1])
        except Exception as exc:
            raise LLMError(f"fine-tuned model generation failed: {exc}") from exc

        # The model was trained on single turns; anything after a new "### "
        # header is it starting to invent the next turn.
        # The model sometimes writes its end-of-text marker as literal text.
        answer = text.split("\n### ")[0].split("</s>")[0].strip()
        if not answer:
            raise LLMError("fine-tuned model returned an empty answer")
        return answer
