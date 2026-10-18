"""Load your shop from a Google Sheet that you published to the web as CSV.

  python import_csv.py --graph my_shop \
      --sheet-customers URL --sheet-sales URL --sheet-payments URL [--sheet-promises URL]

In Google Sheets: File, Share, Publish to web, pick one tab, choose "Comma-separated
values (.csv)", Publish, and copy the link. Do that for each tab. The tabs use the same
columns as the CSV files (see README, "Use it on your own shop").

The links are fetched and written to a temporary folder as customers.csv, sales.csv,
payments.csv and promises.csv, then loaded by the same loader and checks as the CSV path.
Only https://docs.google.com/spreadsheets/ links are ever fetched. Redirects are followed
only when they also point at docs.google.com/spreadsheets. Size and time are limited.
"""
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ALLOWED_HOST = "docs.google.com"
ALLOWED_PREFIX = "/spreadsheets/"
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15
MAX_REDIRECTS = 3
KINDS = ("customers", "sales", "payments", "promises")


class SheetProblem(Exception):
    pass


def check_sheet_url(url):
    """Return the clean URL, or raise SheetProblem. Never accepts any other host."""
    if not isinstance(url, str) or len(url) > 2000 or any(c in url for c in "\r\n\t "):
        raise SheetProblem("That is not a usable link.")
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https":
        raise SheetProblem("The link must start with https://docs.google.com/spreadsheets/")
    if p.username is not None or p.password is not None:
        raise SheetProblem("The link must not contain a user name or password.")
    if p.hostname != ALLOWED_HOST:
        raise SheetProblem("Only links on docs.google.com are accepted, not '%s'." % (p.hostname or ""))
    try:
        port = p.port
    except ValueError:
        raise SheetProblem("The link has a bad port number.")
    if port not in (None, 443):
        raise SheetProblem("The link must use the normal https port.")
    if not p.path.startswith(ALLOWED_PREFIX):
        raise SheetProblem("The link must be a Google Sheets link (docs.google.com/spreadsheets/...).")
    return urllib.parse.urlunsplit(("https", ALLOWED_HOST, p.path, p.query, ""))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def decode_sheet(body):
    """Bytes from Google to CSV text, or raise SheetProblem."""
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SheetProblem("The sheet could not be read as text.")
    if text.lstrip()[:1] == "<":
        raise SheetProblem("Google sent a web page, not CSV. Publish the tab to the web as CSV "
                           "(File, Share, Publish to web, Comma-separated values) and use that link.")
    return text


def fetch_csv(url, opener=None):
    """Fetch one published sheet tab as CSV text. `opener` is only for tests."""
    url = check_sheet_url(url)
    opener = opener or urllib.request.build_opener(_NoRedirect)
    for _ in range(MAX_REDIRECTS + 1):
        req = urllib.request.Request(url, headers={"User-Agent": "bashi-sheet-import"})
        try:
            with opener.open(req, timeout=TIMEOUT) as r:
                body = r.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise SheetProblem("The sheet is bigger than %d MB." % (MAX_BYTES // (1024 * 1024)))
            return decode_sheet(body)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = check_sheet_url(urllib.parse.urljoin(url, e.headers["Location"]))
                continue
            raise SheetProblem("Google answered with error %d. Is the tab published to the web?" % e.code)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SheetProblem("Could not reach Google Sheets (%s)." % getattr(e, "reason", e))
    raise SheetProblem("Too many redirects.")


def load_sheets(urls, graph_name, replace=False, db=None, fetch=fetch_csv):
    """urls: {'customers': URL, 'sales': URL, 'payments': URL, 'promises': URL optional}.
    Same loader and checks as the CSV path."""
    from import_csv import load_csv_dir
    missing = [k for k in ("customers", "sales", "payments") if not urls.get(k)]
    if missing:
        raise SheetProblem("Missing link(s) for: %s" % ", ".join(missing))
    clean = {k: check_sheet_url(u) for k, u in urls.items() if u}
    with tempfile.TemporaryDirectory() as tmp:
        for kind, u in clean.items():
            text = fetch(u)
            with open(os.path.join(tmp, kind + ".csv"), "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        return load_csv_dir(tmp, graph_name, replace=replace, db=db)
