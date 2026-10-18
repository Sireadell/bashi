"""Google Sheets import: the link check and the parsing. Google is never called here."""
import io
import urllib.error
from pathlib import Path

import pytest

import import_csv
import sheets

GOOD = "https://docs.google.com/spreadsheets/d/e/2PACX-abc123/pub?gid=0&single=true&output=csv"
SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "my_shop_csv"


def test_good_google_url_accepted():
    assert sheets.check_sheet_url(GOOD) == GOOD
    assert sheets.check_sheet_url("https://docs.google.com:443/spreadsheets/d/x/export?format=csv")


@pytest.mark.parametrize("url", [
    "http://docs.google.com/spreadsheets/d/e/x/pub?output=csv",
    "https://docs.google.com.evil.com/spreadsheets/d/e/x/pub?output=csv",
    "https://evil.com/spreadsheets/d/e/x/pub?output=csv",
    "https://evildocs.google.com/spreadsheets/d/e/x",
    "https://docs.google.com@evil.com/spreadsheets/d/e/x",
    "https://evil.com@docs.google.com/spreadsheets/d/e/x",
    "https://docs.google.com:8443/spreadsheets/d/e/x",
    "https://docs.google.com/document/d/x",
    "https://docs.google.com/spreadsheetsX/d/x",
    "https://drive.google.com/spreadsheets/d/x",
    r"https://docs.google.com\@evil.com/spreadsheets/d/x",
    "file:///etc/passwd",
    "ftp://docs.google.com/spreadsheets/d/x",
    "https://localhost/spreadsheets/d/x",
    "https://127.0.0.1/spreadsheets/d/x",
    "",
    None,
    "https://docs.google.com/spreadsheets/d/x y",
])
def test_other_hosts_and_lookalikes_rejected(url):
    with pytest.raises(sheets.SheetProblem):
        sheets.check_sheet_url(url)


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Opener:
    def __init__(self, *outcomes):
        self.outcomes, self.seen = list(outcomes), []

    def open(self, req, timeout=None):
        self.seen.append(req.full_url)
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return FakeResp(o)


def redirect(to):
    from email.message import Message
    h = Message()
    h["Location"] = to
    return urllib.error.HTTPError(GOOD, 302, "Found", h, None)


def test_redirect_to_other_host_is_refused():
    op = Opener(redirect("https://evil.com/spreadsheets/x"))
    with pytest.raises(sheets.SheetProblem):
        sheets.fetch_csv(GOOD, opener=op)
    assert op.seen == [GOOD]            # evil.com was never requested


def test_redirect_within_google_is_followed():
    op = Opener(redirect("https://docs.google.com/spreadsheets/d/e/other/pub?output=csv"), b"id,name\nA,B\n")
    assert sheets.fetch_csv(GOOD, opener=op).startswith("id,name")
    assert len(op.seen) == 2


def test_html_page_and_too_big_rejected():
    with pytest.raises(sheets.SheetProblem, match="web page"):
        sheets.fetch_csv(GOOD, opener=Opener(b"<!DOCTYPE html><html>Sign in</html>"))
    with pytest.raises(sheets.SheetProblem, match="bigger"):
        sheets.fetch_csv(GOOD, opener=Opener(b"a" * (sheets.MAX_BYTES + 5)))


def test_missing_link_refused_before_any_fetch():
    def boom(u):
        raise AssertionError("fetched")
    with pytest.raises(sheets.SheetProblem, match="payments"):
        sheets.load_sheets({"customers": GOOD, "sales": GOOD}, "my_shop", fetch=boom)


def test_other_host_refused_before_any_fetch():
    def boom(u):
        raise AssertionError("fetched")
    bad = {"customers": GOOD, "sales": GOOD, "payments": "https://docs.google.com.evil.com/spreadsheets/d/x"}
    with pytest.raises(sheets.SheetProblem):
        sheets.load_sheets(bad, "my_shop", fetch=boom)


def test_sheet_text_is_parsed_by_the_csv_checks(tmp_path, monkeypatch):
    """Fetched text goes through the same read_csv_folder as the CSV path (no database needed)."""
    texts = {k: (SAMPLE / (k + ".csv")).read_text(encoding="utf-8") for k in
             ("customers", "sales", "payments", "promises")}
    urls = {k: GOOD + "&kind=" + k for k in texts}
    seen = {}

    def fake_fetch(u):
        return texts[u.rsplit("=", 1)[1]]

    def fake_load(folder, graph, replace=False, db=None):
        seen["rows"] = import_csv.read_csv_folder(folder)
        return {"ok": True}

    monkeypatch.setattr(import_csv, "load_csv_dir", fake_load)
    assert sheets.load_sheets(urls, "my_shop", fetch=fake_fetch) == {"ok": True}
    assert len(seen["rows"]["customers"]) >= 2 and seen["rows"]["sales"] and seen["rows"]["payments"]


def test_bad_rows_in_a_sheet_are_reported_not_loaded(monkeypatch):
    texts = {"customers": "id,name,credit_limit\nC1,A,abc\n", "sales": "id,customer_id,amount,date\n",
             "payments": "id,customer_id,amount,date\n"}
    urls = {k: GOOD + "&kind=" + k for k in texts}
    with pytest.raises(import_csv.ImportProblems):
        sheets.load_sheets(urls, "my_shop", fetch=lambda u: texts[u.rsplit("=", 1)[1]],
                           db=object())
