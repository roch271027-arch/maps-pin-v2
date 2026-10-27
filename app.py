from flask import Flask, request, jsonify, send_from_directory
import requests
import re
import html
from urllib.parse import urlparse, unquote, urljoin

app = Flask(__name__, static_folder="static")

ALLOWED = {
    "maps.app.goo.gl",
    "goo.gl",
    "www.google.com",
    "google.com",
    "maps.google.com",
}

def valid_coords(lat, lng):
    try:
        lat = float(lat)
        lng = float(lng)
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return [lat, lng]
    except (ValueError, TypeError):
        pass
    return None

def extract(value):
    s = html.unescape(unquote(str(value)))
    s = s.replace("\\u003d", "=").replace("\\u0026", "&")
    s = s.replace("\\/", "/")

    patterns = [
        r'!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)',
        r'!2d(-?\d+(?:\.\d+)?)!3d(-?\d+(?:\.\d+)?)',
        r'[?&](?:q|query|ll|center)=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)',
        r'@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)',
        r'"latitude"\s*:\s*(-?\d+(?:\.\d+)?).*?"longitude"\s*:\s*(-?\d+(?:\.\d+)?)',
        r'"lat"\s*:\s*(-?\d+(?:\.\d+)?).*?"lng"\s*:\s*(-?\d+(?:\.\d+)?)',
    ]

    for i, pattern in enumerate(patterns):
        match = re.search(pattern, s, re.I | re.S)
        if match:
            a, b = match.groups()
            if i == 1:
                coords = valid_coords(b, a)
            else:
                coords = valid_coords(a, b)
            if coords:
                return coords

    return None

def safe_url(url):
    try:
        p = urlparse(url)
        return (
            p.scheme == "https"
            and (p.hostname or "").lower() in ALLOWED
            and p.username is None
            and p.password is None
            and p.port in (None, 443)
        )
    except ValueError:
        return False

@app.get("/")
def index():
    return send_from_directory("static", "index.html")

@app.post("/api/resolve")
def resolve():
    data = request.get_json(silent=True) or {}
    value = str(data.get("url", "")).strip()

    if not value:
        return jsonify(error="กรุณากรอกลิงก์หรือพิกัด"), 400

    if len(value) > 2000:
        return jsonify(error="ข้อมูลยาวเกินไป"), 400

    # วิธีที่ 1: กรอกตัวเลขพิกัดโดยตรง
    if re.fullmatch(
        r'-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?',
        value
    ):
        coords = valid_coords(*value.split(","))
        if coords:
            return jsonify(lat=coords[0], lng=coords[1])
        return jsonify(error="ตัวเลขพิกัดไม่ถูกต้อง"), 400

    # วิธีที่ 2: วางลิงก์ Google Maps
    if not safe_url(value):
        return jsonify(
            error="รองรับเฉพาะลิงก์ HTTPS ของ Google Maps"
        ), 400

    coords = extract(value)
    if coords:
        return jsonify(
            lat=coords[0],
            lng=coords[1],
            resolved_url=value
        )

    try:
        current = value

        with requests.Session() as session:
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 13) "
                    "AppleWebKit/537.36 "
                    "Chrome/120.0 Mobile Safari/537.36"
                ),
                "Accept-Language": "th-TH,th;q=0.9,en;q=0.8"
            })

            for _ in range(10):
                if not safe_url(current):
                    return jsonify(
                        error="ลิงก์เปลี่ยนไปยังเว็บไซต์ที่ไม่รองรับ"
                    ), 400

                response = session.get(
                    current,
                    allow_redirects=False,
                    timeout=10,
                    stream=True
                )

                try:
                    location = response.headers.get("Location")

                    if location:
                        next_url = urljoin(current, location)

                        if not safe_url(next_url):
                            return jsonify(
                                error="ลิงก์เปลี่ยนไปยังเว็บไซต์ที่ไม่รองรับ"
                            ), 400

                        current = next_url
                        coords = extract(current)

                        if coords:
                            return jsonify(
                                lat=coords[0],
                                lng=coords[1],
                                resolved_url=current
                            )
                        continue

                    if response.status_code != 200:
                        break

                    chunks = []
                    total = 0

                    for chunk in response.iter_content(16384):
                        if total + len(chunk) > 2_000_000:
                            chunks.append(
                                chunk[:2_000_000 - total]
                            )
                            break
                        chunks.append(chunk)
                        total += len(chunk)

                    page = b"".join(chunks).decode(
                        "utf-8", errors="replace"
                    )

                    coords = extract(page)

                    if coords:
                        return jsonify(
                            lat=coords[0],
                            lng=coords[1],
                            resolved_url=current
                        )

                    # บางหน้าใช้การเปลี่ยนเส้นทางผ่าน HTML
                    match = re.search(
                        r'<meta[^>]+http-equiv=["\']refresh["\']'
                        r'[^>]+content=["\'][^"\']*url=([^"\']+)',
                        page,
                        re.I
                    )

                    if match:
                        next_url = urljoin(
                            current,
                            html.unescape(match.group(1))
                        )
                        if safe_url(next_url):
                            current = next_url
                            continue

                    break

                finally:
                    response.close()

        return jsonify(
            error=(
                "ยังไม่พบพิกัดจากลิงก์นี้ "
                "กรุณาลองลิงก์เต็มหรือกรอกตัวเลขพิกัด"
            )
        ), 422

    except requests.RequestException:
        return jsonify(
            error="เชื่อมต่อ Google Maps ไม่สำเร็จ กรุณาลองใหม่"
        ), 502

if __name__ == "__main__":
    app.run(debug=True)