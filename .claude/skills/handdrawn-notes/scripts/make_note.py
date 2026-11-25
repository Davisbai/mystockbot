"""Generate a Japanese hand-drawn note infographic with Gemini.

Usage: python3 -I make_note.py content.md out.png [--style cards|rich] [--ratio 1:1] [--no-ref] [--model NAME]
"""
import argparse, base64, json, os, pathlib, sys, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
REFS = {"cards": ASSETS / "reference_parenting.jpg", "rich": ASSETS / "reference_rich_threeviews.jpg"}
DEFAULT_RATIO = {"cards": "1:1", "rich": "3:2"}
API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

STYLE_CARDS = """請畫一張「日系手繪筆記圖」資訊圖，風格與附圖完全一致（只學版型與畫風，內容換成下面的新內容）：
- 米白手工紙底，粉彩水彩暈染（粉紅、鵝黃、淡藍、薄荷綠），細黑墨線
- 頂部中央：粗黑手寫主標題（兩行可），下方黃色螢光筆底線
- 多張圓角手繪卡片分區排版，卡片標題用粉彩色塊或紙膠帶裝飾
- 「小標｜說明」格式：畫成粗體小標，換行接較小的說明字，不要畫出「｜」符號
- 清單用 ☑ 勾選框、♥、圓點；轉變用「從 X → Y」與弧形箭頭
- 溫柔日系插畫人物（半身、表情柔和），點綴愛心、嫩芽、星星、小旗
- 文字全部是清楚正確的手寫繁體中文，嚴格照下面給的字，不要自行增字、不要英文、不要日期、簽名或浮水印
- 留白充足、資訊層次清楚、不擁擠

內容：
規則：【】內是版面提示（用哪種元素），只照做、絕不要把【】內文字畫出來；### 後的文字才是要畫出的區塊標題。每個字都要清楚正確，寧可字少字大，不要擠出模糊或亂碼的小字。人物頭像不要沿用參考圖的人物，依內容重新畫。循環圖的節點數量與文字必須和提示完全一致，不可多畫或重複節點。不要畫任何社群平台 logo 或圖示。
"""


STYLE_RICH = """請畫一張「豐富版日系手繪筆記圖」橫式資訊海報，風格與附圖完全一致（只學版型與畫風，內容換成下面的新內容）：
- 背景是淡雅水彩風景：遠山、雲霧、日出、櫻花枝或楓葉點綴在角落，米白紙質感
- 左上：超大粗黑書法感主標題＋紅色小印章，下方兩行副標，螢光筆底線；角落小字標註來源
- 頂部中央可放一句引言卡（人物素描頭像＋引號）
- 各段用「一、二、三…」編號，標題放在紫色或藍色毛筆刷色帶上（白字或深字）
- 正中央放核心概念圖：3–4 個水彩圓形節點用彩色弧形箭頭繞成循環，中心寫核心詞
- 版面元素混用：橫向一排 3–4 格小人物插畫卡（每格標籤＋括號說明）、兩人對話泡泡中間大紅色 ≠、三列表格（圖示＋名稱＋說明）、「例：」情境小圖＋紅框警示卡、木頭路標（✓ 條列）、螺旋筆記本勾選清單＋鋼筆、黃色便利貼重點卡
- 人物插畫：背包客坐在山頭看日出等寫意場景，日系水彩、細墨線
- 最底部一條紫色毛筆橫幅，用 → 串起整篇的因果鏈
- 資訊密度高但分區清楚；文字全部是清楚正確的繁體中文，嚴格照下面給的字，不要自行增字、不要英文（來源帳號除外）、不要日期或浮水印

內容：
規則：【】內是版面提示（用哪種元素），只照做、絕不要把【】內文字畫出來；### 後的文字才是要畫出的區塊標題。每個字都要清楚正確，寧可字少字大，不要擠出模糊或亂碼的小字。人物頭像不要沿用參考圖的人物，依內容重新畫。循環圖的節點數量與文字必須和提示完全一致，不可多畫或重複節點。不要畫任何社群平台 logo 或圖示。
"""

STYLES = {"cards": STYLE_CARDS, "rich": STYLE_RICH}


def call(model, parts, ratio):
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"],
                                 "imageConfig": {"aspectRatio": ratio, **({"imageSize": "2K"} if "pro" in model else {})}}}
    req = urllib.request.Request(API.format(model), json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "x-goog-api-key": os.environ.get("GEMINI_API_KEY", "proxy-injected")})
    r = json.load(urllib.request.urlopen(req, timeout=300))
    for p in r["candidates"][0]["content"]["parts"]:
        if "inlineData" in p:
            return base64.b64decode(p["inlineData"]["data"])
    raise RuntimeError("no image returned")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("content"); ap.add_argument("out")
    ap.add_argument("--style", choices=["cards", "rich"], default="cards")
    ap.add_argument("--ratio")
    ap.add_argument("--no-ref", action="store_true")
    ap.add_argument("--model")
    a = ap.parse_args()
    parts = []
    ratio = a.ratio or DEFAULT_RATIO[a.style]
    ref = REFS[a.style]
    if not a.no_ref and ref.exists():
        parts.append({"inline_data": {"mime_type": "image/jpeg",
                                      "data": base64.b64encode(ref.read_bytes()).decode()}})
    parts.append({"text": STYLES[a.style] + pathlib.Path(a.content).read_text(encoding="utf-8")})
    models = [a.model] if a.model else ["gemini-3-pro-image-preview", "gemini-2.5-flash-image"]
    for m in models:
        try:
            pathlib.Path(a.out).write_bytes(call(m, parts, ratio))
            print(f"saved {a.out} ({m})"); return
        except Exception as e:
            print(f"{m} failed: {e}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
