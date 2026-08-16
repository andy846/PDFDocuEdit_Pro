import json
import sys
import urllib.error
import urllib.request

TOKEN = sys.argv[1]
request = urllib.request.Request(
    "https://api.github.com/repos/andy846/PDFDocuEdit_Pro",
    data=json.dumps({"private": False}).encode("utf-8"),
    headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github+json",
        "User-Agent": "PDFDocuEdit-Pro",
        "Content-Type": "application/json",
    },
    method="PATCH",
)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
        print("VISIBILITY:", data.get("private"), "html_url:", data.get("html_url"))
except urllib.error.HTTPError as exc:
    print("HTTP", exc.code, exc.read().decode("utf-8", errors="replace")[:300])
