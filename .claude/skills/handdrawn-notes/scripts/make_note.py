"""Generate a Japanese hand-drawn note infographic with Gemini.

Usage: python3 -I make_note.py content.md out.png [--ratio 1:1] [--no-ref] [--model NAME]
"""
import argparse, base64, json, pathlib, sys, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
REF = HERE.parent / "assets" / "reference_parenting.jpg"
API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

STYLE = """請畫一張「日系手繪筆記圖」資訊圖，風格與附圖完全一致（只學版型與畫風，內容換成下面的新內容）：
- 米白手工紙底，粉彩水彩暈染（粉紅、鵝黃、淡藍、薄荷綠），細黑墨線
- 頂部中央：粗黑手寫主標題（兩行可），下方黃色螢光筆底線
- 多張圓角手繪卡片分區排版，卡片標題用粉彩色塊或紙膠帶裝飾
- 「小標｜說明」格式：畫成粗體小標，換行接較小的說明字，不要畫出「｜」符號
- 清單用 ☑ 勾選框、♥、圓點；轉變用「從 X → Y」與弧形箭頭
- 溫柔日系插畫人物（半身、表情柔和），點綴愛心、嫩芽、星星、小旗
- 文字全部是清楚正確的手寫繁體中文，嚴格照下面給的字，不要自行增字、不要英文、不要日期、簽名或浮水印
- 留白充足、資訊層次清楚、不擁擠

內容（### 為各卡片，請自行安排在合適位置）：
"""


def call(model, parts, ratio):
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"],
                                 "imageConfig": {"aspectRatio": ratio}}}
    req = urllib.request.Request(API.format(model), json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "x-goog-api-key": "proxy-injected"})
    r = json.load(urllib.request.urlopen(req, timeout=300))
    for p in r["candidates"][0]["content"]["parts"]:
        if "inlineData" in p:
            return base64.b64decode(p["inlineData"]["data"])
    raise RuntimeError("no image returned")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("content"); ap.add_argument("out")
    ap.add_argument("--ratio", default="1:1")
    ap.add_argument("--no-ref", action="store_true")
    ap.add_argument("--model")
    a = ap.parse_args()
    parts = []
    if not a.no_ref and REF.exists():
        parts.append({"inline_data": {"mime_type": "image/jpeg",
                                      "data": base64.b64encode(REF.read_bytes()).decode()}})
    parts.append({"text": STYLE + pathlib.Path(a.content).read_text(encoding="utf-8")})
    models = [a.model] if a.model else ["gemini-3-pro-image-preview", "gemini-2.5-flash-image"]
    for m in models:
        try:
            pathlib.Path(a.out).write_bytes(call(m, parts, a.ratio))
            print(f"saved {a.out} ({m})"); return
        except Exception as e:
            print(f"{m} failed: {e}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
