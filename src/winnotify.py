"""Windows notifications (replaces Telegram): « 3 nouvelles offres retenues » with the best-rated ones.

Each offer is announced once (data/notifiees.json, local). The first call only records the
offers already there, so you are not flooded with the backlog.
"""
import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTIFIED_PATH = ROOT / "data" / "notifiees.json"

_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $xml.GetElementsByTagName('text')
$t.Item(0).AppendChild($xml.CreateTextNode('__TITLE__')) > $null
$t.Item(1).AppendChild($xml.CreateTextNode('__BODY__')) > $null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def toast(title, body):
    """Show a Windows notification. Does nothing (returns False) outside Windows."""
    if sys.platform != "win32":
        return False
    esc = lambda s: (s or "").replace("'", "''")
    script = _PS.replace("__TITLE__", esc(title)[:120]).replace("__BODY__", esc(body)[:300])
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                       capture_output=True, timeout=30, creationflags=0x08000000)
        return True
    except Exception:
        return False


def _load(path):
    try:
        return set(json.loads(Path(path).read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def message_for(new_offers):
    best = sorted(new_offers, key=lambda o: (o.get("score") is not None, o.get("score") or 0), reverse=True)[:2]
    lines = []
    for o in best:
        stars = f"⭐{o['score']} " if o.get("score") is not None else ""
        lines.append(f"{stars}{(o.get('title') or '')[:45]} · {(o.get('company') or '')[:25]}")
    title = f"💼 {len(new_offers)} nouvelle(s) offre(s) retenue(s)"
    return title, "\n".join(lines)


def notify_new_offers(path=None, notify=toast):
    """Announce relevant, untouched offers not announced yet. Returns how many were announced."""
    from . import tracking
    path = Path(path or NOTIFIED_PATH)
    offers = [o for o in tracking.load_offers()
              if o.get("relevancy_check") == "relevant" and o.get("status") == "À regarder"]
    ids = {o["id"] for o in offers}
    known = _load(path)
    new = [o for o in offers if known is not None and o["id"] not in known]
    if new:
        notify(*message_for(new))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted((known or set()) | ids)), encoding="utf-8")
    return len(new)
