"""Part 6.4: voice end to end against a running server: Kannada audio -> STT -> chat -> TTS,
then one long text through /voice/speak to check sentence splitting and WAV joining.
usage: _part6_voice.py <base> <server_log>"""
import base64, io, json, sys, time, wave
import httpx

BASE, LOG = sys.argv[1], sys.argv[2]
c = httpx.Client(base_url=BASE, timeout=600)
tok = c.post("/auth/login", json={"phone": "9999999999", "password": "demo1234"}).json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}
out = {}

def wav_seconds(b):
    with wave.open(io.BytesIO(b)) as w:
        return round(w.getnframes() / w.getframerate(), 1)

def tts_log(n_before):
    lines = [l for l in open(LOG, encoding="utf-8", errors="replace") if "TTS:" in l]
    return [l.strip()[-200:] for l in lines[n_before:]]

n = len(tts_log(0))
t = time.time()
r = c.post("/voice/ask", headers=H, data={"farm_id": "1"},
           files={"audio": ("speech.webm", open("test_runs/voice_question_kn.webm", "rb").read(), "audio/webm")})
d = r.json()
audio = base64.b64decode(d.get("audio_base64") or "")
out["ask"] = {"http": r.status_code, "seconds": round(time.time() - t, 1), "transcript": d.get("transcript"),
              "language": d.get("language"), "answer_chars": len(d.get("answer") or ""),
              "answer": d.get("answer"), "audio_bytes": len(audio),
              "audio_seconds": wav_seconds(audio) if audio else 0, "tts_log": tts_log(n)}
open("test_runs/part6_voice_answer.wav", "wb").write(audio)
print("ASK:", r.status_code, out["ask"]["seconds"], "s | transcript:", d.get("transcript"),
      "| answer chars", out["ask"]["answer_chars"], "| audio", out["ask"]["audio_bytes"], "bytes,",
      out["ask"]["audio_seconds"], "s |", out["ask"]["tts_log"])

long_text = ("ಪ್ರತಿ ನೀರಾವರಿಗೆ ಸುಮಾರು 7 ರಿಂದ 8 ಸೆಂಟಿಮೀಟರ್ ನೀರು ಹಾಕಬೇಕು. " * 6
             + "Each irrigation should apply about 7 to 8 cm of water, adjusted for rainfall and soil type. " * 6)
n = len(tts_log(0))
t = time.time()
r = c.post("/voice/speak", headers=H, json={"text": long_text, "language": "kn"})
audio = base64.b64decode(r.json().get("audio_base64") or "") if r.status_code == 200 else b""
out["long"] = {"http": r.status_code, "seconds": round(time.time() - t, 1), "text_chars": len(long_text),
               "audio_bytes": len(audio), "audio_seconds": wav_seconds(audio) if audio else 0,
               "tts_log": tts_log(n)}
open("test_runs/part6_voice_long.wav", "wb").write(audio)
print("LONG:", out["long"])
json.dump(out, open("test_runs/part6_voice.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
