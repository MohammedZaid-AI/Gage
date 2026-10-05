"""Does a system-prompt steer make the fine-tuned model answer an ENGLISH
question in Kanglish? Loads the model once, tries a few prompt variants."""
import os
import sys

sys.path.insert(0, ".")
os.environ.setdefault("LLM_PROVIDER", "groq")   # don't auto-build any engine

import torch  # noqa: E402

from backend.ai.providers.sarvam_llm import SarvamFinetunedLLMProvider  # noqa: E402

p = SarvamFinetunedLLMProvider()
tok, model, dev = p._tokenizer, p._model, p._device

CONTEXT = ("Irrigation water depth of 7-8 cm per application is recommended, with frequency "
           "varying by crop stage: about every 7 days during germination, every 10 days during "
           "tillering. Skip-furrow irrigation can save roughly 30-40% of water.")
QUESTION = "Should I irrigate?"

VARIANTS = {
    "baseline (current)":
        "You are Gage, an AI assistant that provides accurate, practical agricultural "
        "advice in Kannada-English.",
    "direct kanglish command":
        "You are Gage, an agricultural assistant for Karnataka sugarcane farmers. Always "
        "reply in Kanglish: Kannada spoken in Latin letters mixed with English words "
        "(like 'Sir, neeru 7-8 cm hakbeku'). Never reply in pure English or in Kannada "
        "script, whatever language the farmer uses.",
    "kanglish command + example":
        "You are Gage, an agricultural assistant for Karnataka sugarcane farmers. You must "
        "ALWAYS answer in Kanglish (romanized Kannada in Latin letters mixed with English), "
        "even if the farmer writes in English. Example style: 'Nodi sir, prati irrigation ge "
        "7-8 cm neeru hakbeku, timing correct maadidre hecchu phala bartade.'",
}


def generate(system: str, question: str, context: str) -> str:
    prompt = f"### System\n{system}\n\n### Context\n{context}\n\n### Farmer\n{question}\n\n### Assistant\n"
    inputs = tok(prompt, return_tensors="pt").to(dev)
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=90, do_sample=False,
                             repetition_penalty=1.1, pad_token_id=tok.pad_token_id,
                             eos_token_id=tok.eos_token_id)
    text = tok.decode(out[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    return text.split("\n### ")[0].split("</s>")[0].strip()


print(f"QUESTION (English): {QUESTION}\n")
for name, system in VARIANTS.items():
    print(f"--- {name}")
    print(generate(system, QUESTION, CONTEXT), "\n", flush=True)

# Also: an inline hint appended to the farmer's turn, baseline system prompt.
print("--- baseline system + inline '(answer in Kanglish)' hint")
hinted = QUESTION + "\n(Reply in Kanglish: romanized Kannada mixed with English.)"
print(generate(VARIANTS["baseline (current)"], hinted, CONTEXT), flush=True)
