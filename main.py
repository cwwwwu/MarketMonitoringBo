import os
import tweepy
import telegram
import asyncio
import re
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError
from transformers import pipeline

# ---------------------------
# CẤU HÌNH CHUNG - SỬ DỤNG BIẾN MÔI TRƯỜNG (nếu triển khai trên Railway)
# Nếu chạy cục bộ bạn có thể thay thế trực tiếp bằng giá trị dưới đây.
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8068020647:AAF4Axc47chC_W6WD4NFM-RmUK0EltClyzo')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '6175539694')
BEARER_TOKEN = os.environ.get('BEARER_TOKEN', 'AAAAAAAAAAAAAAAAAAAAAG4RygEAAAAAYJtH3r1yWJr3Sf4c9ivWYM3MvWk%3DxErhWdtPMwaYC9gQ7EWZ4oBvJyakGiyJjBo5yPXjGwBhuQ1jQf')

bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
client = tweepy.Client(bearer_token=BEARER_TOKEN)

# ---------------------------
# DANH SÁCH TÀI KHOẢN TRÊN X
# ---------------------------
accounts = [
    "financialjuice",
    "RadarHits",
    "elonmusk",
    "ali_charts",
    "DeItaone",
    "Reuters",
    "Investingcom"
]
query = " OR ".join([f"from:{acc}" for acc in accounts])

# ---------------------------
# CẤU HÌNH PHÂN LOẠI THỊ TRƯỜNG
# ---------------------------
gold_keywords   = ["gold", "xau", "giá vàng", "gold price"]
crypto_keywords = ["crypto", "bitcoin", "btc", "ethereum", "eth", "coin"]
forex_keywords  = ["forex", "fx", "eur/usd", "usd", "eur", "gbp", "jpy"]

# ---------------------------
# GLOBAL VARIABLES
# ---------------------------
last_tweet_id = None
processed_tweet_ids = set()
# Lưu trữ tweet cho từng lĩnh vực
tweets_data = {
    "gold": [],
    "crypto": [],
    "forex": []
}

# ---------------------------
# KHỞI TẠO PIPELINE AI
# ---------------------------
summarization_pipeline = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")
text_gen_pipeline = pipeline("text-generation", model="distilgpt2")

# ---------------------------
# HÀM TRÍCH XUẤT THÔNG TIN THỊ TRƯỜNG
# ---------------------------
def extract_market_info(market: str, texts: list) -> str:
    combined_text = " ".join(texts)
    if market == "gold":
        match = re.search(r"\$\d{1,3}(?:,\d{3})*(?:\.\d+)?", combined_text)
        return f"Giá vàng: {match.group(0)}" if match else "Chưa có dữ liệu giá vàng."
    elif market == "crypto":
        coins = []
        for coin in ["BTC", "ETH", "XRP", "LTC", "ADA"]:
            if re.search(rf"\b{coin}\b", combined_text, re.IGNORECASE):
                coins.append(coin)
        return "Mã coin: " + ", ".join(coins) if coins else "Chưa có dữ liệu mã coin."
    elif market == "forex":
        pairs = re.findall(r"\b[A-Z]{3}/[A-Z]{3}\b", combined_text)
        return "Các cặp tiền: " + ", ".join(set(pairs)) if pairs else "Chưa có dữ liệu forex."
    else:
        return "Không xác định."

# ---------------------------
# HÀM TÓM TẮT VĂN BẢN
# ---------------------------
async def summarize_text(text: str) -> str:
    if len(text.split()) < 20:
        return text
    result = await asyncio.to_thread(summarization_pipeline, text)
    return result[0]['summary_text'] if result else ""

# ---------------------------
# HÀM SINH KHÁNH NGHỊ TỪ AI
# ---------------------------
async def generate_recommendation(market: str, summary_text: str) -> str:
    prompt = f"Dựa trên tóm tắt tin tức về {market} dưới đây, hãy đưa ra khuyến nghị tài chính ngắn gọn:\nTóm tắt: {summary_text}\nKhuyến nghị:"
    result = await asyncio.to_thread(text_gen_pipeline, prompt, max_length=100, do_sample=True)
    generated = result[0]['generated_text']
    recommendation = generated.replace(prompt, "").strip()
    return recommendation if recommendation else "Không có khuyến nghị."

# ---------------------------
# HÀM LẤY VÀ PHÂN LOẠI TWEET
# ---------------------------
async def fetch_and_classify_tweets():
    global last_tweet_id, processed_tweet_ids, tweets_data
    query_params = {
        "query": query,
        "expansions": ["author_id"],
        "tweet_fields": ["id", "text", "created_at"],
        "user_fields": ["username"],
        "max_results": 50
    }
    if last_tweet_id:
        query_params["since_id"] = last_tweet_id

    try:
        tweets = client.search_recent_tweets(**query_params)
        await asyncio.sleep(2)
    except tweepy.errors.TooManyRequests as e:
        print("Twitter API rate limit reached. Sleeping for 900 seconds.")
        await asyncio.sleep(900)
        return
    except Exception as e:
        print(f"Error querying Twitter: {e}")
        return

    if tweets.data is None:
        return

    last_tweet_id = tweets.data[0].id

    for tweet in tweets.data:
        if tweet.id in processed_tweet_ids:
            continue
        processed_tweet_ids.add(tweet.id)
        text = tweet.text.lower()
        # Phân loại tweet dựa trên từ khóa
        for kw in gold_keywords:
            if kw in text:
                tweets_data["gold"].append(tweet.text)
                break
        for kw in crypto_keywords:
            if kw in text:
                tweets_data["crypto"].append(tweet.text)
                break
        for kw in forex_keywords:
            if kw in text:
                tweets_data["forex"].append(tweet.text)
                break
        await asyncio.sleep(0.5)

# ---------------------------
# HÀM XỬ LÝ VÀ GỬI BÁO CÁO
# ---------------------------
async def process_market(market: str, tweets_list: list) -> dict:
    if not tweets_list:
        return {"summary": "Không có dữ liệu.", "market_info": "Không có dữ liệu.", "recommendation": "Không có dữ liệu."}
    combined_text = " ".join(tweets_list)
    summary_text = await summarize_text(combined_text)
    market_info = extract_market_info(market, tweets_list)
    recommendation = await generate_recommendation(market, summary_text)
    return {"summary": summary_text, "market_info": market_info, "recommendation": recommendation}

async def send_report():
    global tweets_data
    gold_report = await process_market("gold", tweets_data["gold"])
    crypto_report = await process_market("crypto", tweets_data["crypto"])
    forex_report = await process_market("forex", tweets_data["forex"])

    report_lines = []
    for market, report in zip(["Gold", "Crypto", "Forex"], [gold_report, crypto_report, forex_report]):
        report_lines.append(f"*{market}*")
        report_lines.append(f"_Tóm tắt tin tức:_ {report['summary']}")
        report_lines.append(f"_Thông tin thị trường:_ {report['market_info']}")
        report_lines.append(f"_Khuyến nghị từ AI:_ {report['recommendation']}")
        report_lines.append("")
    final_report = "📊 *Báo cáo tài chính cập nhật (mỗi 15 phút):*\n" + "\n".join(report_lines)
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=final_report,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
    except RetryAfter as e:
        wait_time = e.retry_after + 1
        print(f"Telegram rate limit. Sleeping for {wait_time} seconds.")
        await asyncio.sleep(wait_time)
    except TelegramError as e:
        print(f"Telegram error: {e}")
        await asyncio.sleep(10)
    except Exception as e:
        print(f"Error sending report: {e}")
    # Reset dữ liệu cho chu kỳ mới
    for key in tweets_data:
        tweets_data[key] = []

async def main():
    while True:
        await fetch_and_classify_tweets()
        await send_report()
        print("Cycle complete. Sleeping for 15 minutes...")
        await asyncio.sleep(900)

if __name__ == "__main__":
    asyncio.run(main())
