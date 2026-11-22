#!/usr/bin/env python3
"""用 Gemini 圖像模型生成/修改手繪圖。用法見 SKILL.md。"""
import argparse, base64, json, sys, urllib.request, urllib.error

MODELS = ["gemini-nano-banana-2.1", "gemini-3.1-flash-image",
          "gemini-3-pro-image", "gemini-2.5-flash-image"]
BASE = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

ap = argparse.ArgumentParser()
ap.add_argument("prompt_file"); ap.add_argument("out")
ap.add_argument("--aspect", default="16:9")
ap.add_argument("--model"); ap.add_argument("--edit", help="要修改的原圖 PNG")
a = ap.parse_args()

parts = [{"text": open(a.prompt_file, encoding="utf-8").read()}]
if a.edit:
    parts.insert(0, {"inlineData": {"mimeType": "image/png",
                 "data": base64.b64encode(open(a.edit, "rb").read()).decode()}})
body = json.dumps({"contents": [{"parts": parts}], "generationConfig": {
    "responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": a.aspect}}}).encode()

for m in ([a.model] if a.model else MODELS):
    req = urllib.request.Request(BASE.format(m), body, {
        "x-goog-api-key": "dummy", "Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=300))
        for p in d["candidates"][0]["content"]["parts"]:
            if "inlineData" in p:
                open(a.out, "wb").write(base64.b64decode(p["inlineData"]["data"]))
                print(f"ok model={m} -> {a.out}"); sys.exit(0)
        print(f"{m}: no image returned", file=sys.stderr)
    except (urllib.error.URLError, KeyError, IndexError) as e:
        print(f"{m}: {e}", file=sys.stderr)
sys.exit(1)
