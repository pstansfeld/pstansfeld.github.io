#!/usr/bin/env python3
"""Refresh group/publications.html from PubMed.

Run weekly by .github/workflows/update-publications.yml. Replaces everything
between the PUBS:START and PUBS:END markers in the page; the rest of the page
(header, menu, intro) is left alone. Standard library only.
"""
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

TERM = "Stansfeld PJ[au]"          # PubMed author search
ME = "Stansfeld PJ"                # shown in bold in author lists
MIN_PAPERS = 50                    # refuse to publish a suspiciously short list
PAGE = Path(__file__).resolve().parents[2] / "group" / "publications.html"
START, END = "<!-- PUBS:START -->", "<!-- PUBS:END -->"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
SKIP_TYPES = {"Published Erratum", "Preprint", "Retraction of Publication", "Expression of Concern"}
TITLE_TAGS = {"i", "b", "sup", "sub", "u"}


def eutils(endpoint, **params):
    params.update(tool="stansfeld-group-site")
    url = EUTILS + endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "stansfeld-group-site (+https://pstansfeld.github.io/group/)"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # network blip, NCBI busy or rate limit: back off and retry
            body = e.read(300).decode("utf-8", "replace") if hasattr(e, "read") else ""
            print(f"  {endpoint} attempt {attempt + 1} failed: {e} {body!r}", file=sys.stderr)
            if attempt == 4:
                raise
            time.sleep(10 * (attempt + 1))


def fetch_ids():
    res = json.loads(eutils("esearch.fcgi", db="pubmed", term=TERM, retmax=1000, retmode="json"))
    return res["esearchresult"]["idlist"]


def fetch_records(ids):
    out = []
    for i in range(0, len(ids), 100):
        out.append(eutils("efetch.fcgi", db="pubmed", id=",".join(ids[i:i + 100]), retmode="xml"))
        time.sleep(1)
    return out


def inner(el):
    """Element text as safe HTML, keeping only simple inline formatting."""
    if el is None:
        return ""
    out = [html.escape(el.text or "", quote=False)]
    for c in el:
        body = inner(c)
        out.append(f"<{c.tag}>{body}</{c.tag}>" if c.tag in TITLE_TAGS else body)
        out.append(html.escape(c.tail or "", quote=False))
    return re.sub(r"\s+", " ", "".join(out)).strip()


def txt(el, path):
    found = el.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def authors(art):
    names = []
    for a in art.findall("AuthorList/Author"):
        if txt(a, "LastName"):
            names.append(f"{txt(a, 'LastName')} {txt(a, 'Initials')}".strip())
        elif txt(a, "CollectiveName"):
            names.append(txt(a, "CollectiveName"))
    if len(names) > 25:  # long consortium lists: first ten, the PI, last author
        short = names[:10] + ["…"]
        if ME in names[10:-1]:
            short += [ME, "…"]
        names = short + names[-1:]
    s = html.escape(", ".join(names).replace(", …,", " …").replace(", …", " …"), quote=False)
    return s.replace(ME, f"<b>{ME}</b>")


def parse(xml_text):
    papers = []
    for pa in ET.fromstring(xml_text).findall("PubmedArticle"):
        mc = pa.find("MedlineCitation")
        art = mc.find("Article")
        types = {t.text for t in art.findall("PublicationTypeList/PublicationType")}
        if types & SKIP_TYPES:
            continue
        title = inner(art.find("ArticleTitle")).rstrip(".")
        if not title:
            continue
        ji = art.find("Journal/JournalIssue")
        year = txt(ji, "PubDate/Year") or (re.findall(r"\d{4}", txt(ji, "PubDate/MedlineDate")) or [""])[0] \
            or txt(art, "ArticleDate/Year")
        if not year:
            continue
        vol, issue, pages = txt(ji, "Volume"), txt(ji, "Issue"), txt(art, "Pagination/MedlinePgn")
        details = year
        if vol:
            details += f";{vol}" + (f"({issue})" if issue else "")
        if pages:
            details += f":{pages}"
        doi = ""
        for aid in pa.findall("PubmedData/ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi" and aid.text:
                doi = aid.text.strip()
        if not doi:
            for loc in art.findall("ELocationID"):
                if loc.get("EIdType") == "doi" and loc.text:
                    doi = loc.text.strip()
        pmid = txt(mc, "PMID")
        url = f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        papers.append({
            "pmid": int(pmid), "year": int(year), "title": title, "authors": authors(art),
            "journal": html.escape(txt(art, "Journal/ISOAbbreviation") or txt(art, "Journal/Title"), quote=False),
            "details": html.escape(details, quote=False), "url": html.escape(url),
        })
    return papers


def render(papers):
    by_year = {}
    for p in sorted(papers, key=lambda p: (p["year"], p["pmid"]), reverse=True):
        by_year.setdefault(p["year"], []).append(p)
    lines = ['<ul class="years" aria-label="Jump to year">']
    lines += [f'  <li><a href="#y{y}">{y}</a></li>' for y in by_year]
    lines.append("</ul>")
    for y, ps in by_year.items():
        lines.append(f'<h2 class="pub-year" id="y{y}">{y}</h2>')
        lines.append('<ol class="pubs">')
        for p in ps:
            lines += [
                "  <li>",
                f'    <a class="t" href="{p["url"]}">{p["title"]}</a>',
                f'    <p class="a">{p["authors"]}</p>',
                f'    <p class="j"><em>{p["journal"]}</em> {p["details"]}</p>',
                "  </li>",
            ]
        lines.append("</ol>")
    return "\n".join(lines)


def update_page(page_html, papers, today=None):
    today = today or date.today()
    if START not in page_html or END not in page_html:
        raise SystemExit(f"Markers {START} / {END} not found in {PAGE}")
    stamp = (f'<p class="updated">{len(papers)} papers · checked against '
             f'<a href="https://pubmed.ncbi.nlm.nih.gov/?term={urllib.parse.quote(TERM)}">PubMed</a> '
             f'on {today.day} {today:%B %Y}</p>')
    block = f"{START}\n{stamp}\n{render(papers)}\n{END}"
    head, rest = page_html.split(START, 1)
    _, tail = rest.split(END, 1)
    # keep the page's indentation for the block
    indent = re.search(r"[ \t]*$", head).group(0)
    block = block.replace("\n", "\n" + indent)
    return head + block + tail


def main():
    ids = fetch_ids()
    print(f"PubMed returned {len(ids)} records for {TERM!r}")
    papers = [p for chunk in fetch_records(ids) for p in parse(chunk)]
    print(f"Kept {len(papers)} papers")
    if len(papers) < MIN_PAPERS:
        raise SystemExit(f"Only {len(papers)} papers found (expected at least {MIN_PAPERS}); leaving the page unchanged.")
    PAGE.write_text(update_page(PAGE.read_text(encoding="utf-8"), papers), encoding="utf-8")
    print(f"Wrote {PAGE}")


if __name__ == "__main__":
    main()
