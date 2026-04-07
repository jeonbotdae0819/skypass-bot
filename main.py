import requests
import time
import schedule
import logging
import random
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# =============================================
# ✈️ 설정 영역 - 여기만 수정하세요!
# =============================================

TELEGRAM_TOKEN = "8782698522:AAGv4f0KxG9Yc5YEFlpxsrgCxTHRXO3yFBI"
TELEGRAM_CHAT_ID = "1192284673"

ROUTES = {
    "유럽": [
        ("ICN", "LHR"), ("ICN", "CDG"), ("ICN", "FRA"),
        ("ICN", "AMS"), ("ICN", "FCO"), ("ICN", "MAD"),
        ("ICN", "BCN"), ("ICN", "VIE"), ("ICN", "ZRH"), ("ICN", "CPH"),
    ],
    "미주": [
        ("ICN", "JFK"), ("ICN", "LAX"), ("ICN", "ORD"),
        ("ICN", "SFO"), ("ICN", "SEA"), ("ICN", "ATL"),
        ("ICN", "BOS"), ("ICN", "YVR"), ("ICN", "YYZ"),
    ],
}

CHECK_ECONOMY   = True
CHECK_BUSINESS  = True
CHECK_FIRST     = False
SEARCH_MONTHS_AHEAD = 6
CHECK_INTERVAL_MINUTES = 10

# =============================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)
already_notified = set()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        if r.status_code == 200:
            log.info("텔레그램 알림 전송 성공")
        else:
            log.warning(f"텔레그램 전송 실패: {r.status_code} {r.text}")
    except Exception as e:
        log.error(f"텔레그램 오류: {e}")


def send_startup_message():
    routes_text = ""
    for region, routes in ROUTES.items():
        codes = ", ".join(f"{o}→{d}" for o, d in routes)
        routes_text += f"\n  [{region}] {codes}"
    classes = []
    if CHECK_ECONOMY:  classes.append("이코노미")
    if CHECK_BUSINESS: classes.append("비즈니스")
    if CHECK_FIRST:    classes.append("퍼스트")
    msg = (
        f"✈️ <b>스카이패스 마일리지 알림봇 시작!</b>\n\n"
        f"📍 모니터링 노선:{routes_text}\n\n"
        f"💺 좌석 등급: {', '.join(classes)}\n"
        f"📅 검색 범위: 오늘 ~ {SEARCH_MONTHS_AHEAD}개월 후\n"
        f"⏱ 체크 주기: {CHECK_INTERVAL_MINUTES}분마다\n\n"
        f"마일리지 좌석이 나오면 바로 알려드릴게요! 🔔"
    )
    send_telegram(msg)


def get_search_dates():
    dates = []
    today = datetime.today()
    for m in range(SEARCH_MONTHS_AHEAD):
        d = today + timedelta(days=30 * m)
        dates.append(d.strftime("%Y%m%d"))
    return dates


def make_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    })
    try:
        session.get("https://www.koreanair.com", timeout=10)
        time.sleep(random.uniform(2, 4))
    except Exception:
        pass
    return session


def check_mileage_seats(session, origin, destination, date):
    url = (
        "https://www.koreanair.com/booking/availability"
        f"?dep={origin}&arr={destination}&depDate={date}"
        "&adult=1&child=0&infant=0&tripType=OW&cabin=Y&bookingType=AWARD"
    )
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code == 403:
            log.warning(f"403 차단: {origin}→{destination} 세션 재시작")
            return None
        if resp.status_code != 200:
            log.warning(f"응답 오류 {resp.status_code}: {origin}→{destination}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        found_seats = []
        cabin_map = []
        if CHECK_ECONOMY:  cabin_map.append(("Y", "이코노미"))
        if CHECK_BUSINESS: cabin_map.append(("C", "비즈니스"))
        if CHECK_FIRST:    cabin_map.append(("F", "퍼스트"))

        for cabin_code, cabin_name in cabin_map:
            for seat in soup.select(f"[data-cabin='{cabin_code}'][data-award='true']"):
                if seat.get("data-available", "false") == "true":
                    miles = seat.get("data-miles", "")
                    if miles:
                        found_seats.append({"class": cabin_name, "miles": miles, "seats": seat.get("data-seats", "")})
        return found_seats
    except requests.exceptions.Timeout:
        log.warning(f"타임아웃: {origin}→{destination}")
        return []
    except Exception as e:
        log.warning(f"오류 {origin}→{destination}: {e}")
        return []


def check_all_routes():
    log.info("===== 전체 노선 체크 시작 =====")
    dates = get_search_dates()
    found_any = False
    session = make_session()

    for region, routes in ROUTES.items():
        for origin, destination in routes:
            for date in dates:
                log.info(f"체크 중: {origin}→{destination} ({date})")
                seats = check_mileage_seats(session, origin, destination, date)

                if seats is None:
                    time.sleep(random.uniform(8, 15))
                    session = make_session()
                    seats = check_mileage_seats(session, origin, destination, date) or []

                for seat in seats:
                    key = f"{origin}-{destination}-{date}-{seat['class']}"
                    if key in already_notified:
                        continue
                    already_notified.add(key)
                    found_any = True
                    date_fmt = f"{date[:4]}.{date[4:6]}.{date[6:]}"
                    seat_info = f" ({seat['seats']}석 남음)" if seat["seats"] else ""
                    msg = (
                        f"🚨 <b>마일리지 좌석 발견!</b>\n\n"
                        f"✈️ 노선: {origin} → {destination} [{region}]\n"
                        f"📅 날짜: {date_fmt}\n"
                        f"💺 등급: {seat['class']}{seat_info}\n"
                        f"🏆 필요 마일리지: {seat['miles']} miles\n\n"
                        f"👉 <a href='https://www.koreanair.com/booking/availability"
                        f"?dep={origin}&arr={destination}&depDate={date}"
                        f"&bookingType=AWARD'>지금 바로 예약하기</a>\n\n"
                        f"⏰ 발견 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    send_telegram(msg)
                    log.info(f"알림 전송: {origin}→{destination} {date} {seat['class']}")

                time.sleep(random.uniform(3, 7))

    if not found_any:
        log.info("이번 체크: 마일리지 좌석 없음")
    log.info("===== 체크 완료 =====\n")


if __name__ == "__main__":
    log.info("스카이패스 마일리지 알림봇 시작")
    send_startup_message()
    check_all_routes()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_all_routes)
    while True:
        schedule.run_pending()
        time.sleep(30)
