import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import sys
import re
import json
import time
import urllib.parse
import os
import unicodedata
import difflib
import io
import contextlib

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    NoSuchWindowException
)

# ============================================================
# 基本設定（グローバル変数）
# ============================================================
INPUT_FILE = "stations.json"
OUTPUT_FILE = "station_updated.json"
PAGE_TIMEOUT = 20
RETRY_WAIT = 5
REQUEST_INTERVAL = 3
MAX_RETRIES = None
SEARCH_WAIT = 1.5
DETAIL_WAIT = 1.5
MIN_ACCEPT_SCORE = 400
VERBOSE = False

# ストップ信号用フラグ
STOP_REQUESTED = False

# ============================================================
# コンソール出力の画面転送クラス
# ============================================================
class TextRedirector:
    def __init__(self, text_widget, status_label, progress_var, root):
        self.text_widget = text_widget
        self.status_label = status_label
        self.progress_var = progress_var
        self.root = root

    def write(self, str_data):
        if "\r" in str_data:
            clean_text = str_data.replace("\r", "").strip()
            if clean_text:
                self.root.after(0, self.update_status, clean_text)
                if "\n" in str_data:
                    self.root.after(0, self.append_text, clean_text + "\n")
        else:
            self.root.after(0, self.append_text, str_data)

    def update_status(self, text):
        self.status_label.config(text=text)
        match = re.search(r"\[(\d+)/(\d+)\]", text)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            if total > 0:
                self.progress_var.set((current / total) * 100)

    def append_text(self, text):
        self.text_widget.insert(tk.END, text)
        self.text_widget.see(tk.END)

    def flush(self):
        pass

def status(text):
    sys.stdout.write("\r" + " " * 90 + "\r" + text)
    sys.stdout.flush()

def status_done(text):
    sys.stdout.write("\r" + " " * 90 + "\r" + text + "\n")
    sys.stdout.flush()

# ============================================================
# スクレイピング処理（裏側で動く機能）
# ============================================================
def create_driver():
    print("\nChromeを起動しています...")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    )
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(PAGE_TIMEOUT)
        print("Chromeの起動に成功しました。")
        return driver
    except Exception as e:
        print("\n========================================")
        print("Chromeの起動に失敗しました")
        print("========================================")
        print(e)
        raise

def to_hiragana(text):
    result = []
    for char in text:
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            result.append(chr(code - 0x60))
        else:
            result.append(char)
    return "".join(result)

def to_katakana(text):
    result = []
    for char in text:
        code = ord(char)
        if 0x3041 <= code <= 0x3096:
            result.append(chr(code + 0x60))
        else:
            result.append(char)
    return "".join(result)

SMALL_KANA_MAP = str.maketrans({
    "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お", "っ": "つ",
    "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "ゎ": "わ", "ヵ": "か", "ヶ": "け", "ゔ": "う",
})

VARIANT_KANJI_MAP = str.maketrans({
    "髙": "高", "﨑": "崎", "祥": "祥", "澤": "沢", "濱": "浜", "邊": "辺",
    "齋": "斎", "廣": "広", "櫻": "桜", "嶋": "島", "瀧": "滝", "槇": "槙",
    "塚": "塚", "冨": "富", "﨟": "腊", "之": "の", "ヶ": "け", "ケ": "け",
})

def unify_variants(text):
    text = text.translate(SMALL_KANA_MAP)
    text = text.translate(VARIANT_KANJI_MAP)
    return text

def normalize_text(text):
    if not text: return ""
    text = str(text).strip().lower()
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r"[ー〜~−-]", "", text)
    text = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return text

def normalize_station_name(text):
    text = normalize_text(text)
    text = text.replace("道の駅", "")
    return text

def normalize_for_fuzzy(text):
    text = normalize_station_name(text)
    text = to_hiragana(text)
    text = unify_variants(text)
    return text

def validate_coordinates(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
        if not (20 <= lat <= 46): return False
        if not (120 <= lon <= 150): return False
        return True
    except (ValueError, TypeError):
        return False

def create_search_url(keyword):
    encoded_keyword = urllib.parse.quote(keyword)
    return f"https://www.navitime.co.jp/freeword/?keyword={encoded_keyword}"

def load_page(driver, url, page_name):
    print(f"\n{page_name}\nURL: {url}")
    try:
        driver.get(url)
    except TimeoutException:
        print(f"{page_name}の読み込みがタイムアウトしました。")
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass
    try:
        WebDriverWait(driver, PAGE_TIMEOUT).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except TimeoutException:
        raise RuntimeError(f"{page_name}のbodyを取得できませんでした。")
    time.sleep(SEARCH_WAIT)

def calculate_match_score(station_name, candidate_text):
    target_normal = normalize_station_name(station_name)
    candidate_normal = normalize_station_name(candidate_text)
    target_fuzzy = normalize_for_fuzzy(station_name)
    candidate_fuzzy = normalize_for_fuzzy(candidate_text)
    
    if not target_normal or not candidate_normal:
        return 0

    score = 0
    for target, candidate in ((target_normal, candidate_normal), (target_fuzzy, candidate_fuzzy)):
        if not target or not candidate: continue
        if target == candidate:
            score = max(score, 1000)
            continue
        if target in candidate:
            length_penalty = max(0, len(candidate) - len(target))
            score = max(score, max(800, 900 - length_penalty * 2))
            continue
        if candidate in target:
            score = max(score, 700)
            continue

        similarity = difflib.SequenceMatcher(None, target, candidate).ratio()
        if similarity >= 0.9: score = max(score, 850)
        elif similarity >= 0.8: score = max(score, 700)
        elif similarity >= 0.7: score = max(score, 550)
        elif similarity >= 0.6: score = max(score, 400)

        common_chars = sum(1 for char in target if char in candidate)
        if common_chars > 0:
            ratio = common_chars / len(target)
            if ratio >= 0.8: score = max(score, 500)
            elif ratio >= 0.6: score = max(score, 300)
    return score

def find_best_poi_url(soup, station_name, search_url):
    candidates = []
    first_poi_url = None  # 追加: 検索結果の1番上のURLを記憶しておく用

    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "")
        if "/poi?spot=" not in href: continue
        
        full_url = urllib.parse.urljoin(search_url, href)
        
        # 【追加】最初に見つけた施設URLをキープしておく
        if not first_poi_url:
            first_poi_url = full_url
            
        text = a_tag.get_text(" ", strip=True)
        score = calculate_match_score(station_name, text)
        
        parent = a_tag.parent
        parent_text = parent.get_text(" ", strip=True) if parent else ""
        parent_score = calculate_match_score(station_name, parent_text)
        
        if parent_score > score:
            score = min(parent_score, 950)
            
        if score > 0:
            candidates.append({"score": score, "text": text, "url": full_url})

    # まずはこれまで通り、名前が一致するもの（スコアが高いもの）を探す
    if candidates:
        candidates.sort(key=lambda x: x["score"], reverse=True)
        print("\n検索候補:")
        for candidate in candidates[:10]:
            print(f"  スコア={candidate['score']} 名称={candidate['text']} URL={candidate['url']}")
            
        best = candidates[0]
        # スコアが基準（MIN_ACCEPT_SCORE）以上ならそれを採用
        if best["score"] >= MIN_ACCEPT_SCORE:
            print(f"\n最有力候補: {best['text']}\n一致スコア: {best['score']}")
            return best["url"]

    # 【追加】名前が一致しなかった場合（候補ゼロ、またはスコアが低すぎる場合）、
    # 検索結果に施設があれば1番目を強制的に採用する
    if first_poi_url:
        print(f"\n[妥協案を採用] 名前が十分に一致しませんでしたが、検索結果の先頭URLを取得します。")
        return first_poi_url

    return None

def extract_coordinates(detail_soup):
    dl_tags = detail_soup.find_all("dl", class_="detail-text-frame")
    for dl in dl_tags:
        dt_tag = dl.find("dt", class_="detail-text-frame__title")
        if not dt_tag: continue
        title = normalize_text(dt_tag.get_text(" ", strip=True))
        if "緯度経度" not in title: continue
        dd_tag = dl.find("dd", class_="detail-text-frame__body")
        if not dd_tag: continue
        
        lat_lon_text = dd_tag.get_text(" ", strip=True)
        print(f"緯度経度欄: {lat_lon_text}")
        numbers = re.findall(r"-?\d+(?:\.\d+)?", lat_lon_text)
        if len(numbers) >= 2:
            lat = float(numbers[0])
            lon = float(numbers[1])
            if validate_coordinates(lat, lon):
                return lat, lon
            raise RuntimeError(f"取得した座標が日本国内の妥当な範囲ではありません。 lat={lat}, lon={lon}")

    page_text = detail_soup.get_text(" ", strip=True)
    match = re.search(r"緯度経度.{0,100}?(-?\d+\.\d+)\s*[,，]\s*(-?\d+\.\d+)", page_text)
    if match:
        lat = float(match.group(1))
        lon = float(match.group(2))
        if validate_coordinates(lat, lon): return lat, lon
    raise RuntimeError("詳細ページから緯度経度を取得できませんでした。")

def get_coordinates_from_url(driver, target_url):
    print(f"\n詳細ページ: {target_url}")
    try:
        driver.get(target_url)
    except TimeoutException:
        print("詳細ページの読み込みがタイムアウトしました。")
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass
    try:
        WebDriverWait(driver, PAGE_TIMEOUT).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except TimeoutException:
        raise RuntimeError("詳細ページのbodyを取得できませんでした。")
    time.sleep(DETAIL_WAIT)
    
    detail_soup = BeautifulSoup(driver.page_source, "html.parser")
    return extract_coordinates(detail_soup)

def create_search_keywords(station_name, pref=""):
    keywords = []
    bare_name = normalize_text(station_name).replace("道の駅", "")
    hiragana_name = to_hiragana(bare_name)
    katakana_name = to_katakana(bare_name)

    if pref:
        keywords.extend([f"{pref} 道の駅 {station_name}", f"{pref} 道の駅{station_name}", f"{pref} {station_name}"])
        
    keywords.extend([
        f"道の駅 {station_name}", station_name, f"道の駅「{station_name}」", f"道の駅{station_name}"
    ])
    
    if hiragana_name: keywords.extend([f"道の駅 {hiragana_name}", hiragana_name])
    if katakana_name: keywords.extend([f"道の駅 {katakana_name}", katakana_name])
    if bare_name: keywords.append(bare_name)

    result = []
    for keyword in keywords:
        if keyword and keyword not in result:
            result.append(keyword)
    return result

def get_lat_lon_with_selenium(driver, station_name, pref):
    search_keywords = create_search_keywords(station_name, pref)
    print("\n検索候補キーワード:")
    for keyword in search_keywords: print(f"  ・{keyword}")

    for keyword_index, keyword in enumerate(search_keywords, start=1):
        print(f"\n----------------------------------------\n検索方法 {keyword_index}/{len(search_keywords)}\n検索語: {keyword}\n----------------------------------------")
        search_url = create_search_url(keyword)
        print(f"検索URL: {search_url}")
        
        load_page(driver, search_url, "検索ページ")
        soup = BeautifulSoup(driver.page_source, "html.parser")
        target_url = find_best_poi_url(soup, station_name, search_url)
        
        if not target_url:
            print("この検索方法では一致する候補が見つかりませんでした。")
            continue
            
        try:
            lat, lon = get_coordinates_from_url(driver, target_url)
            return lat, lon
        except Exception as e:
            print("\n詳細ページからの座標取得に失敗しました。")
            print(e)
            continue
            
    raise RuntimeError(f"「{station_name}」に一致するNAVITIMEの道の駅を見つけられませんでした。")

def get_coordinates_until_success(driver, station_name, pref, station_index, total_count):
    retry_count = 0
    while True:
        retry_count += 1
        if retry_count == 1:
            status(f"[{station_index}/{total_count}] {station_name} を検索中...")
        else:
            status(f"[{station_index}/{total_count}] {station_name} 再試行 {retry_count} 回目...")
            
        try:
            if VERBOSE:
                lat, lon = get_lat_lon_with_selenium(driver, station_name, pref)
            else:
                with contextlib.redirect_stdout(io.StringIO()):
                    lat, lon = get_lat_lon_with_selenium(driver, station_name, pref)
            return driver, lat, lon
        except (WebDriverException, NoSuchWindowException) as e:
            status_done(f"[Chromeエラー] {station_name}: {type(e).__name__} -> Chromeを再起動します")
            try: driver.quit()
            except Exception: pass
            time.sleep(3)
            driver = create_driver()
        except Exception as e:
            status_done(f"[取得失敗] {station_name}: {e}")
            
        if MAX_RETRIES is not None and retry_count >= MAX_RETRIES:
            raise RuntimeError(f"「{station_name}」の取得に{MAX_RETRIES}回失敗しました。")
            
        if VERBOSE: print(f"\n{RETRY_WAIT}秒待って再試行します...")
        time.sleep(RETRY_WAIT)

def save_json(data, output_file):
    temp_file = output_file + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        try: os.fsync(f.fileno())
        except Exception: pass
    os.replace(temp_file, output_file)

# ============================================================
# メイン処理（バックグラウンド実行用）
# ============================================================
def run_scraping():
    global STOP_REQUESTED
    print("=" * 60 + "\n道の駅 緯度経度自動取得プログラム\n" + "=" * 60)

    # 再開時は station_updated.json があればそちらを読み込む
    target_file = OUTPUT_FILE if os.path.exists(OUTPUT_FILE) else INPUT_FILE
    
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"\nエラー: {target_file} が見つかりません。")
        return
    except json.JSONDecodeError as e:
        print("\nエラー: JSONファイルが壊れています。\n", e)
        return

    stations = data.get("stations", [])
    if not stations:
        print("\nエラー: stationsが空です。")
        return

    total_count = len(stations)
    print(f"\n合計 {total_count:,} 件の道の駅を処理します。")
    print(f"読み込み元ファイル: {target_file}")

    driver = create_driver()
    success_count = 0
    start_time = time.time()

    try:
        for i, station in enumerate(stations):
            if STOP_REQUESTED:
                print("\n[中断] ストップボタンが押されたため、安全に処理を停止しました。")
                break

            station_name = station.get("name")
            
            # ------------------------------------------------
            # 【修正】元のデータにlat/lonがあってもスキップしない。
            # ただし、このプログラムで「すでに確認・上書き完了」した印があればスキップする。
            # ------------------------------------------------
            if station.get("_verified"):
                status_done(f"[{i + 1}/{total_count}] スキップ済(確認完了): {station_name}")
                success_count += 1
                continue

            pref = station.get("pref", "")
            if not station_name:
                raise RuntimeError(f"{i + 1}件目のデータにnameがありません。")

            # 緯度経度を取得
            driver, lat, lon = get_coordinates_until_success(driver, station_name, pref, i + 1, total_count)

            # データを上書きして、「確認完了」の印をつける
            station["lat"] = float(lat)
            station["lon"] = float(lon)
            station["_verified"] = True  # このプログラムで確認した証拠
            success_count += 1
            
            save_json(data, OUTPUT_FILE)
            
            status_done(f"[{i + 1}/{total_count}] OK {station_name} ({station['lat']}, {station['lon']})")

            if i + 1 < total_count and not STOP_REQUESTED:
                if VERBOSE: print(f"\nサーバー負荷軽減のため{REQUEST_INTERVAL}秒待機します...")
                status(f"[{i + 1}/{total_count}] 完了 - {REQUEST_INTERVAL}秒待機中...")
                time.sleep(REQUEST_INTERVAL)

    except Exception as e:
        print("\n\n========================================\n重大なエラーが発生しました\n========================================")
        print(e)
        try:
            save_json(data, OUTPUT_FILE)
            print(f"\nここまでの {success_count} 件は保存されています。")
        except Exception as save_error:
            print("\n保存にも失敗しました。\n", save_error)
        raise
    finally:
        try: driver.quit()
        except Exception: pass

    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    if STOP_REQUESTED:
        print("処理を中断しました")
    else:
        print("すべての処理が完了しました")
    print("=" * 60)
    print(f"成功: {success_count:,} / {total_count:,}")
    print(f"処理時間: {elapsed / 60:.1f}分")
    print(f"保存先: {OUTPUT_FILE}")
    print("=" * 60)

# ============================================================
# GUI（画面）の制御
# ============================================================
def stop_scraping(stop_btn, status_lbl):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    stop_btn.config(state=tk.DISABLED)
    status_lbl.config(text="停止処理中...（現在の駅が終了次第停止します）", foreground="red")

def start_scraping(start_btn, stop_btn, status_lbl, progress_var, root):
    global STOP_REQUESTED
    STOP_REQUESTED = False
    start_btn.config(state=tk.DISABLED)
    stop_btn.config(state=tk.NORMAL)
    status_lbl.config(text="Chromeを起動しています...", foreground="blue")
    progress_var.set(0)
    
    def run_script():
        try:
            run_scraping()
        except Exception as e:
            print(f"\n[致命的なエラー] {e}")
        finally:
            root.after(0, lambda: start_btn.config(state=tk.NORMAL))
            root.after(0, lambda: stop_btn.config(state=tk.DISABLED))
            root.after(0, lambda: status_lbl.config(text="処理が完全に停止しました。", foreground="black"))

    thread = threading.Thread(target=run_script)
    thread.daemon = True
    thread.start()

def main_gui():
    root = tk.Tk()
    root.title("道の駅 緯度経度自動取得ツール")
    root.geometry("1200x900")
    root.configure(padx=30, pady=30)

    style = ttk.Style()
    style.configure("Huge.TButton", font=("メイリオ", 40, "bold"), padding=20)

    title_label = ttk.Label(root, text="緯度経度 取得状況", font=("メイリオ", 60, "bold"))
    title_label.pack(side=tk.TOP, anchor="w", pady=(0, 20))

    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(root, variable=progress_var, maximum=100)
    progress_bar.pack(side=tk.TOP, fill="x", pady=(0, 20))

    status_label = ttk.Label(root, text="待機中...", font=("メイリオ", 40), foreground="blue")
    status_label.pack(side=tk.TOP, anchor="w", pady=(0, 20))

    btn_frame = ttk.Frame(root)
    btn_frame.pack(side=tk.BOTTOM, fill="x")

    start_btn = ttk.Button(btn_frame, text="▶ 処理開始", style="Huge.TButton")
    start_btn.pack(side="left", expand=True, fill="x", padx=(0, 20))

    stop_btn = ttk.Button(btn_frame, text="■ ストップ", style="Huge.TButton", state=tk.DISABLED)
    stop_btn.pack(side="right", expand=True, fill="x")

    log_area = scrolledtext.ScrolledText(root, font=("Consolas", 30), bg="#1e1e1e", fg="#d4d4d4")
    log_area.pack(side=tk.TOP, fill="both", expand=True, pady=(0, 30))

    start_btn.config(command=lambda: start_scraping(start_btn, stop_btn, status_label, progress_var, root))
    stop_btn.config(command=lambda: stop_scraping(stop_btn, status_label))

    sys.stdout = TextRedirector(log_area, status_label, progress_var, root)
    sys.stderr = sys.stdout

    root.mainloop()

if __name__ == "__main__":
    main_gui()