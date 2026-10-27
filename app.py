from flask import Flask, request, jsonify, send_from_directory
import requests, re, ipaddress, socket
from urllib.parse import urlparse, unquote

app = Flask(__name__, static_folder='static')
ALLOWED = {'maps.app.goo.gl', 'goo.gl', 'www.google.com', 'google.com', 'maps.google.com'}

def extract(url):
    s = unquote(url)
    patterns = [r'@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)', r'!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)', r'[?&](?:q|query|ll)=(-?\d{1,2}\.\d+)%?2[Cc](-?\d{1,3}\.\d+)', r'[?&](?:q|query|ll)=(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)']
    for p in patterns:
        m = re.search(p, s)
        if m:
            lat, lng = map(float, m.groups())
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return [lat, lng]
    return None

@app.get('/')
def index():
    return send_from_directory('static', 'index.html')

@app.post('/api/resolve')
def resolve():
    url = str((request.get_json(silent=True) or {}).get('url', '')).strip()
    if len(url) > 2000: return jsonify(error='ลิงก์ยาวเกินไป'), 400
    if re.fullmatch(r'\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*', url):
        lat, lng = map(float, url.split(','))
        if -90 <= lat <= 90 and -180 <= lng <= 180: return jsonify(lat=lat, lng=lng)
    parsed = urlparse(url)
    if parsed.scheme != 'https' or (parsed.hostname or '').lower() not in ALLOWED or parsed.username or parsed.password or parsed.port not in (None,443):
        return jsonify(error='รองรับเฉพาะลิงก์ HTTPS ของ Google Maps'), 400
    try:
        # Do not allow arbitrary redirects; validate every redirect destination.
        current = url
        with requests.Session() as session:
            for _ in range(6):
                p = urlparse(current)
                if p.scheme != 'https' or (p.hostname or '').lower() not in ALLOWED:
                    return jsonify(error='ลิงก์เปลี่ยนไปยังโดเมนที่ไม่รองรับ'), 400
                r = session.get(current, allow_redirects=False, timeout=8, headers={'User-Agent':'Mozilla/5.0'}, stream=True)
                next_url = r.headers.get('Location')
                r.close()
                if not next_url:
                    coords = extract(current)
                    if coords: return jsonify(lat=coords[0], lng=coords[1], resolved_url=current)
                    break
                from urllib.parse import urljoin
                current = urljoin(current, next_url)
                coords = extract(current)
                if coords: return jsonify(lat=coords[0], lng=coords[1], resolved_url=current)
        return jsonify(error='ไม่พบพิกัดในลิงก์นี้ ลองเปิด Google Maps แล้วคัดลอกลิงก์แบบเต็มหรือพิกัด'), 422
    except requests.RequestException:
        return jsonify(error='เชื่อมต่อ Google Maps ไม่สำเร็จ กรุณาลองใหม่'), 502

if __name__ == '__main__': app.run(debug=True)
