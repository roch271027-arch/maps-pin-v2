from flask import Flask, request, jsonify, send_from_directory
import requests
import re
import json
from urllib.parse import urlparse, unquote, urljoin

app = Flask(__name__, static_folder="static")

ALLOWED = {
    "maps.app.goo.gl",
    "goo.gl",
    "www.google.com",
    "google.com",
    "maps.google.com"
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
    s = unquote(str(value))

    patterns = [
        r'!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)',
        r'@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)',
        r'[?&](?:q|query|ll|center)=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)',
        r'[?&](?:q|query|ll|center)=(-?\d+(?:\.\d+)?)%2[Cc](-?\d+(?:\.\d+)?)',
        r'"latitude"\s*:\s*(-?\d+(?:\.\d+)?).*?"longitude"\s*:\s*(-?\d+(?:\.\d+)?)',
        r'"lat"\s*:\s*(-?\d+(?:\.\d+)?).*?"lng"\s*:\s*(-?\d+(?:\.\d+)?)'
    ]

    for pattern in patterns:
        match = re.search(pattern, s, re.I | re.S)
        if match:
            coords = valid_coords(*match.groups())
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
    url = str(data.get("url", "")).strip()

    if not url:
        return jsonify(error="กรุณากรอกลิงก์ Google Maps"), 400

    if len(url) > 2000:
        return jsonify(error="ลิงก์ยาวเกินไป"), 400

    if re.fullmatch(
        r'-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?',
        url
    ):
        coords = valid_coords(*url.split(","))
        if coords:
            return jsonify(lat=coords[0], lng=coords[1])

    if not safe_url(url):
        return jsonify(
            error="รองรับเฉพาะลิงก์ HTTPS ของ Google Maps"
        ), 400

    coords = extract(url)
    if coords:
        return jsonify(
            lat=coords[0],
            lng=coords[1],
            resolved_url=url
        )

    try:
        current = url

        with requests.Session() as session:
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 13) "
                    "AppleWebKit/537.36 Chrome/120.0 "
                    "Mobile Safari/537.36"
                ),
                "Accept-Language": "th-TH,th;q=0.9,en;q=0.8"
            })

            for _ in range(8):
                if not safe_url(current):
                    return jsonify(
                        error="ลิงก์เปลี่ยนไปยังโดเมนที่ไม่รองรับ"
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
                                error="ลิงก์เปลี่ยนไปยังโดเมนที่ไม่รองรับ"
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

                    # Read a limited amount of page content.
                    chunks = []
                    total = 0

                    for chunk in response.iter_content(16384):
                        total += len(chunk)
                        if total > 2_000_000:
                            break
                        chunks.append(chunk)

                    html = b"".join(chunks).decode(
                        "utf-8", errors="replace"
                    )

                    coords = extract(html)

                    if coords:
                        return jsonify(
                            lat=coords[0],
                            lng=coords[1],
                            resolved_url=current
                        )

                    break

                finally:
                    response.close()

        return jsonify(
            error=(
                "ยังไม่พบพิกัดในลิงก์นี้ "
                "กรุณาลองใช้ลิงก์เต็มหรือพิกัด"
            )
        ), 422

    except requests.RequestException:
        return jsonify(
            error="เชื่อมต่อ Google Maps ไม่สำเร็จ กรุณาลองใหม่"
        ), 502


if __name__ == "__main__":
    app.run(debug=True)