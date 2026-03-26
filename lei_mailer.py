"""
lei_mailer.py
"""
import os, re, smtplib, requests
from html import escape as _esc
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════
#  CONFIG  (all secrets from environment)
# ═══════════════════════════════════════════════════════════
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
SMTP_USER     = os.environ["SMTP_USER"]
SMTP_PASS     = os.environ["SMTP_PASS"]
MAIL_TO       = os.environ["MAIL_TO"]

API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL   = "groq/compound-mini"

PAGES = [
    ("China",
     "https://www.conference-board.org/topics/business-cycle-indicators/china"),
    ("Germany",
     "https://www.conference-board.org/topics/business-cycle-indicators/germany"),
    ("Japan",
     "https://www.conference-board.org/topics/business-cycle-indicators/japan"),
    ("India",
     "https://www.conference-board.org/topics/business-cycle-indicators/india"),
]

BJ  = timezone(timedelta(hours=8))
NOW = datetime.now(BJ)

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

EMOJI = {"China": "\U0001F1E8\U0001F1F3",
         "Germany": "\U0001F1E9\U0001F1EA",
         "Japan": "\U0001F1EF\U0001F1F5",
         "India": "\U0001F1EE\U0001F1F3"}

# ═══════════════════════════════════════════════════════════
#  1 · SCRAPE
# ═══════════════════════════════════════════════════════════
_ses = requests.Session()
_ses.headers.update(UA)


def fetch(url):
    r = _ses.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def scrape(html):
    """
    Return dict with keys: title, release, lei, cei
    ─────────────────────────────────────────────────
    title   : <meta name="title" content="…">
    release : first <p> inside <span itemprop="articlebody">
              → only the "For Release … yyyy" sentence
    lei     : <p> containing <strong>The Conference Board Leading …
    cei     : <p> containing <strong>The Conference Board Coincident …
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── meta title ───────────────────────────────────────
    m = soup.find("meta", attrs={"name": "title"})
    title = m["content"].strip() if m and m.get("content") else ""

    # ── release line ─────────────────────────────────────
    release = ""
    ab = soup.find("span", itemprop="articlebody")
    if ab:
        for p in ab.find_all("p"):
            txt = p.get_text(" ", strip=True)
            mat = re.search(r"(For Release.+?\d{4})", txt)
            if mat:
                release = mat.group(1)
                break

    # ── LEI / CEI paragraphs ─────────────────────────────
    strongs = soup.find_all("strong")

    def _para(prefix):
        for s in strongs:
            if s.get_text(strip=True).startswith(prefix):
                p = s.find_parent("p")
                return p.get_text(" ", strip=True) if p else ""
        return ""

    lei = _para("The Conference Board Leading Economic Index")
    cei = _para("The Conference Board Coincident Economic Index")

    return dict(title=title, release=release, lei=lei, cei=cei)


# ═══════════════════════════════════════════════════════════
#  2 · TRANSLATE
# ═══════════════════════════════════════════════════════════
def translate(text):
    """Return Chinese str, or None on failure."""
    if not text or not text.strip():
        return ""
    try:
        r = requests.post(
            API_URL,
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system",
                     "content": ("You are a professional English→Chinese "
                                 "translator. Output ONLY the Simplified-"
                                 "Chinese translation, no explanation.")},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.2,
            },
            headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            timeout=180,
        )
        r.raise_for_status()
        out = r.json()["choices"][0]["message"]["content"]
        out = re.sub(r"<think>[\s\S]*?</think>", "", out)
        out = re.sub(r"<think>[\s\S]*$", "", out)
        return out.strip() or None
    except Exception as e:
        print(f"  ⚠  translate error: {e}")
        return None


# ═══════════════════════════════════════════════════════════
#  3 · EMAIL  HTML
# ═══════════════════════════════════════════════════════════
def _field(label, en, cn=None):
    """One labelled block: English + optional Chinese."""
    h = (
        '<tr><td style="padding:16px 32px 0">'
        '<p style="margin:0 0 6px;font-size:11px;font-weight:700;'
        'color:#6366f1;text-transform:uppercase;letter-spacing:1px">'
        f'{_esc(label)}</p>'
        '<p style="margin:0;font-size:15px;line-height:1.8;'
        f'color:#111827">{_esc(en)}</p>'
    )
    if cn:
        h += (
            '<p style="margin:8px 0 0;font-size:15px;line-height:1.8;'
            'color:#374151;border-left:3px solid #e2e8f0;'
            f'padding-left:14px">{_esc(cn)}</p>'
        )
    return h + '</td></tr>'


def _country_block(name, d, cn):
    """HTML section for one country."""
    em = EMOJI.get(name, "\U0001F310")
    s = (
        '<tr><td style="padding:28px 32px 0">'
        '<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        '<td style="border-left:4px solid #6366f1;padding-left:14px">'
        '<h2 style="margin:0;font-size:20px;font-weight:800;'
        f'color:#0f172a">{em} {_esc(name)}</h2>'
        '</td></tr></table></td></tr>'
    )
    if d["title"]:
        s += _field("Title", d["title"],
                     cn.get("title") if cn else None)
    if d["release"]:
        s += _field("Release Date", d["release"])
    if d["lei"]:
        s += _field("Leading Economic Index (LEI)", d["lei"],
                     cn.get("lei") if cn else None)
    if d["cei"]:
        s += _field("Coincident Economic Index (CEI)", d["cei"],
                     cn.get("cei") if cn else None)
    s += (
        '<tr><td style="padding:24px 32px 0">'
        '<hr style="border:none;border-top:1px solid #e5e7eb;margin:0">'
        '</td></tr>'
    )
    return s


def _full_html(body):
    ds = NOW.strftime("%Y-%m-%d")
    ts = NOW.strftime("%Y-%m-%d %H:%M")
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>LEI Update</title>
<!--[if mso]>
<style>body,table,td{{font-family:Arial,sans-serif!important}}</style>
<![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;
-webkit-text-size-adjust:100%;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
'Helvetica Neue',Arial,sans-serif">

<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background-color:#f1f5f9">
<tr><td align="center" style="padding:28px 12px">

<!-- ╔═ CONTAINER ════════════════════════════════════════╗ -->
<table role="presentation" width="640" cellpadding="0" cellspacing="0"
       style="max-width:640px;width:100%;border-collapse:collapse">

<!-- ▌HEADER ──────────────────────────────────────────── -->
<tr><td style="
  background-color:#0F172A;
  background-image:linear-gradient(135deg,
      #0F172A 0%,#1e293b 30%,#334155 60%,#1e293b 80%,#0F172A 100%);
  padding:44px 24px 36px;
  border-radius:16px 16px 0 0;
  text-align:center">
  <h1 style="margin:0;font-size:28px;font-weight:800;
      color:#ffffff;letter-spacing:.3px">
      &#127827;&ensp;LEI Update</h1>
  <p style="margin:12px 0 0;font-size:14px;color:#94a3b8">
      The Conference Board &mdash; Business Cycle Indicators</p>
</td></tr>

<!-- ▌BODY ────────────────────────────────────────────── -->
<tr><td style="background-color:#ffffff">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
{body}
<tr><td style="height:32px"></td></tr>
</table>
</td></tr>

<!-- ▌FOOTER ──────────────────────────────────────────── -->
<tr><td style="
  background-color:#0F172A;
  background-image:linear-gradient(135deg,
      #0F172A 0%,#1e293b 50%,#0F172A 100%);
  padding:30px 24px;
  border-radius:0 0 16px 16px;
  text-align:center">
  <p style="margin:0;font-size:12px;color:#94a3b8;
      letter-spacing:.3px">
      Data updated at {ts} UTC+8</p>
  <p style="margin:10px 0 0;font-size:11px;color:#475569">
      Source&ensp;&#8226;&ensp;The Conference Board&reg;</p>
</td></tr>

</table>
<!-- ╚═ /CONTAINER ═══════════════════════════════════════╝ -->

</td></tr></table>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════
#  4 · SEND
# ═══════════════════════════════════════════════════════════
def send(html_body):
    ds  = NOW.strftime("%Y-%m-%d")
    subj = f"\U0001F353 LEI Update - {ds}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subj
    msg["From"]    = f"Newsletter <{SMTP_USER}>"
    msg["To"]      = MAIL_TO

    # plain-text fallback
    msg.attach(MIMEText(
        "Please view this email in an HTML-capable mail client.",
        "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    to_list = [a.strip() for a in MAIL_TO.split(",")]
    with smtplib.SMTP_SSL("smtp.sohu.com", 465, timeout=30) as srv:
        srv.login(SMTP_USER, SMTP_PASS)
        srv.sendmail(SMTP_USER, to_list, msg.as_string())
    print("\n\u2705  Email sent successfully.")


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════
def main():
    # ── date guard (only for scheduled runs) ─────────────
    if os.environ.get("EVENT_NAME") == "schedule":
        if not (20 <= NOW.day <= 31):
            print(f"\u2139\uFE0F  Beijing day {NOW.day} is outside "
                  f"20-31. Skipping.")
            return

    print(f"\u23F0  {NOW:%Y-%m-%d %H:%M:%S} Beijing Time\n")

    # ── 1) scrape ────────────────────────────────────────
    data = {}
    for name, url in PAGES:
        print(f"\U0001F4E5  Fetching {name} …")
        try:
            data[name] = scrape(fetch(url))
            for k in ("title", "release", "lei", "cei"):
                v = data[name][k]
                tag = f"    {k:8s}\u2502 "
                print(tag + (v[:78] + "\u2026" if len(v) > 78 else v)
                      if v else tag + "(empty)")
        except Exception as e:
            print(f"    \u274C  {e}")
            data[name] = dict(title="", release="", lei="", cei="")
        print()

    # ── 2) translate ─────────────────────────────────────
    cn_all = {}
    ok = True
    for name, _ in PAGES:
        cn = {}
        for key in ("title", "lei", "cei"):
            src = data[name][key]
            if not src:
                cn[key] = ""
                continue
            print(f"\U0001F310  Translating {name}.{key} …")
            result = translate(src)
            if result is None:
                ok = False
                break
            cn[key] = result
            print(f"    \u2192 {result[:78]}"
                  f"{'…' if len(result) > 78 else ''}")
        if not ok:
            break
        cn_all[name] = cn

    if not ok:
        print("\n\u26A0  Translation failed \u2192 "
              "sending English-only email.\n")
        cn_all = {}
    else:
        print()

    # ── 3) build ─────────────────────────────────────────
    blocks = ""
    for name, _ in PAGES:
        blocks += _country_block(name, data[name], cn_all.get(name))
    html = _full_html(blocks)

    # ── 4) send ──────────────────────────────────────────
    send(html)


if __name__ == "__main__":
    main()
