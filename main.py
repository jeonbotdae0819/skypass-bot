import requests
import time
import schedule
import logging
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import json

# =============================================
# ✈️ 설정 영역 - 여기만 수정하세요!
# =============================================

TELEGRAM_TOKEN = "8782698522:AAGv4f0KxG9Yc5YEFlpxsrgCxTHRXO3yFBI"   # @BotFather 에서 받은 토큰
TELEGRAM_CHAT_ID = "1192284673"       # @userinfobot 에서 확인

# 모니터링할 노선 (출발: ICN 고정)
ROUTES = {
    "유럽": [
        ("ICN", "LHR"),  # 런던
        ("ICN", "CDG"),  # 파리
        ("ICN", "FRA"),  # 프랑크푸르트
        ("ICN", "AMS"),  # 암스테르담
        ("ICN", "FCO"),  # 로마
        ("ICN", "MAD"),  # 마드리드
        ("ICN", "BCN"),  # 바르셀로나
        ("ICN", "VIE"),  # 빈
        ("ICN", "ZRH"),  # 취리히
        ("ICN", "CPH"),  # 코펜하겐
    ],
    "미주": [
        ("ICN", "JFK"),  # 뉴욕
        ("ICN", "LAX"),  # 로스앤젤레스
        ("ICN", "ORD"),  # 시카고
        ("ICN", "SFO"),  # 샌프란시스코
        ("ICN", "SEA"),  # 시애틀
        ("ICN", "ATL"),  # 애틀란타
        ("ICN", "BOS"),  # 보스턴
        ("ICN", "YVR"),  # 밴쿠버
        ("ICN", "YYZ"),  # 토론토
    ],
}

# 탑승 클래스 설정 (원하는 것만 True)
CHECK_ECONOMY   = False   # 이코노미 마일리지 좌석
CHECK_BUSINESS  = True   # 비즈니스 마일리지 좌석
CHECK_FIRST     = True  # 퍼스트클래스 마일리지 좌석

# 날짜 범위 설정 (오늘부터 몇 개월 후까지)
SEARCH_MONTHS_AHEAD = 6   # 6개월 후까지 검색

# 체크 주기 (분)
CHECK_INTERVAL_MINUTES = 5

# =============================================
# 로깅 설정
# =============================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("skypass_bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# 알림 중복 방지 (이미 알린 좌석은 다시 알림 안 보냄)
already_notified = set()


# =============================================
# 텔레그램 알림 함수
# =============================================
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            log.info("텔레그램 알림 전송 성공")
        else:
            log.warning(f"텔레그램 전송 실패: {r.text}")
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


# =============================================
# 대한항공 스카이패스 마일리지 좌석 체크
# =============================================
def get_search_dates():
    """오늘부터 SEARCH_MONTHS_AHEAD 개월 후까지 날짜 리스트 반환 (월별)"""
    dates = []
    today = datetime.today()
    for m in range(SEARCH_MONTHS_AHEAD):
        d = today + timedelta(days=30 * m)
        dates.append(d.strftime("%Y%m%d"))
    return dates


def check_mileage_seats(origin: str, destination: str, date: str):
    """
    대한항공 마일리지 좌석 조회 API 호출
    실제 엔드포인트는 대한항공 사이트 구조에 따라 업데이트 필요
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.koreanair.com/",
    }

    # 대한항공 마일리지 좌석 조회 URL
    url = (
        "https://www.koreanair.com/booking/availability"
        f"?dep={origin}&arr={destination}&depDate={date}"
        "&adult=1&child=0&infant=0&tripType=OW&cabin=Y&bookingType=AWARD"
    )

    try:
        session = requests.Session()
        resp = session.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        found_seats = []

        # 이코노미 마일리지 좌석 확인
        if CHECK_ECONOMY:
            econ_seats = soup.select(".award-economy, [data-cabin='Y'][data-award='true']")
            for seat in econ_seats:
                available = seat.get("data-available", "false")
                miles = seat.get("data-miles", "")
                if available == "true" and miles:
                    found_seats.append({
                        "class": "이코노미",
                        "miles": miles,
                        "seats": seat.get("data-seats", ""),
                    })

        # 비즈니스 마일리지 좌석 확인
        if CHECK_BUSINESS:
            biz_seats = soup.select(".award-business, [data-cabin='C'][data-award='true']")
            for seat in biz_seats:
                available = seat.get("data-available", "false")
                miles = seat.get("data-miles", "")
                if available == "true" and miles:
                    found_seats.append({
                        "class": "비즈니스",
                        "miles": miles,
                        "seats": seat.get("data-seats", ""),
                    })

        # 퍼스트 마일리지 좌석 확인
        if CHECK_FIRST:
            first_seats = soup.select(".award-first, [data-cabin='F'][data-award='true']")
            for seat in first_seats:
                available = seat.get("data-available", "false")
                miles = seat.get("data-miles", "")
                if available == "true" and miles:
                    found_seats.append({
                        "class": "퍼스트",
                        "miles": miles,
                        "seats": seat.get("data-seats", ""),
                    })

        return found_seats

    except requests.exceptions.Timeout:
        log.warning(f"타임아웃: {origin}→{destination} {date}")
        return []
    except requests.exceptions.RequestException as e:
        log.warning(f"요청 오류 {origin}→{destination}: {e}")
        return []
    except Exception as e:
        log.error(f"파싱 오류 {origin}→{destination}: {e}")
        return []


# =============================================
# 메인 체크 루프
# =============================================
def check_all_routes():
    log.info("===== 전체 노선 체크 시작 =====")
    dates = get_search_dates()
    found_any = False

    for region, routes in ROUTES.items():
        for origin, destination in routes:
            for date in dates:
                log.info(f"체크 중: {origin}→{destination} ({date})")

                seats = check_mileage_seats(origin, destination, date)

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

                # 요청 간격 (서버 부하 방지)
                time.sleep(2)

    if not found_any:
        log.info("이번 체크: 마일리지 좌석 없음")

    log.info("===== 체크 완료 =====\n")


# =============================================
# 실행
# =============================================
if __name__ == "__main__":
    log.info("스카이패스 마일리지 알림봇 시작")

    # 시작 알림
    send_startup_message()

    # 즉시 한 번 실행
    check_all_routes()

    # 이후 주기적으로 실행
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_all_routes)

    while True:
        schedule.run_pending()
        time.sleep(30)
