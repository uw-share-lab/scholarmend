from __future__ import annotations

from pathlib import Path

from scholarmend.cache import Cache
from scholarmend.http import HttpError
from scholarmend.models import Record
from scholarmend.parse import parse_file
from scholarmend.pipeline import resolve_record
from scholarmend.resolvers.openreview import OpenReviewResolver, abstract_key
from scholarmend.resolvers.proceedings_page import (
    ProceedingsPageResolver,
    abstract_page,
    extract,
    page_key,
)
from scholarmend.resolvers.semanticscholar import SemanticScholarResolver
from scholarmend.resolvers.semanticscholar import abstract_key as s2_key

FIXTURE = Path(__file__).parent / "fixtures" / "sample.ris"
HASH = ("https://proceedings.neurips.cc/paper_files/paper/2025/hash/"
        "3dc85735f6e2fcf093e67b134fa00d21-Abstract-Conference.html")
PDF = ("https://proceedings.neurips.cc/paper_files/paper/2025/file/"
       "3dc85735f6e2fcf093e67b134fa00d21-Paper-Conference.pdf")

# Trimmed from a real proceedings.neurips.cc page; proceedings.iclr.cc is identical.
PAGE = """<html><head>
<meta name="citation_title" content="AgentAuditor: Human-Level Safety &amp; Security Evaluation">
</head><body>
<section class="paper-section">
    <h2 class="section-label">Abstract</h2>
    <p class="paper-abstract"><p>Despite the rapid advancement of <i>LLM</i>-based agents,
    evaluation remains hard &lt;sometimes&gt;.</p><p>Second paragraph.</p>
</p>
</section>
<h4 class="modal-title">Name Change Policy</h4>
</body></html>"""


def test_the_pdf_url_maps_to_its_abstract_page():
    assert abstract_page(PDF) == HASH
    assert abstract_page(HASH) == HASH


def test_a_non_proceedings_url_has_no_abstract_page():
    assert abstract_page("https://openreview.net/forum?id=abc") is None
    assert abstract_page("https://proceedings.neurips.cc/about") is None


def test_extract_reads_the_title_and_a_one_line_abstract():
    got = extract(PAGE)
    assert got["title"] == "AgentAuditor: Human-Level Safety & Security Evaluation"
    assert got["abstract"] == ("Despite the rapid advancement of LLM-based agents, "
                               "evaluation remains hard <sometimes>. Second paragraph.")


def test_extract_of_a_page_without_an_abstract_is_empty_not_wrong():
    assert extract("<html><title>404</title></html>") == {"title": "", "abstract": ""}


def test_the_proceedings_page_claims_the_abstract_from_cache(tmp_path):
    cache = Cache(tmp_path)
    cache.put(page_key(HASH), extract(PAGE))
    claims = ProceedingsPageResolver(cache).resolve(
        "AgentAuditor: Human-Level Safety & Security Evaluation", [PDF])
    assert [c.source for c in claims] == ["proceedings_page"]
    assert claims[0].value.startswith("Despite the rapid advancement")
    assert claims[0].evidence == HASH


def test_a_page_for_a_different_paper_claims_nothing(tmp_path):
    cache = Cache(tmp_path)
    cache.put(page_key(HASH), extract(PAGE))
    assert ProceedingsPageResolver(cache).resolve("A Totally Different Paper", [HASH]) == []


def test_openreview_abstract_is_read_from_its_own_cache_key(tmp_path):
    cache = Cache(tmp_path)
    cache.put(abstract_key("r0BFucF2dH"),
              {"title": "Meta-Router: Bridging Gold-standard and Preference-based Evaluations",
               "abstract": "Full\n abstract."})
    claims = OpenReviewResolver(cache).abstract(
        "r0BFucF2dH", "Meta-Router: Bridging Gold-standard and Preference-based Evaluations")
    assert [(c.value, c.source) for c in claims] == [("Full abstract.", "openreview_api")]


def test_s2_abstract_is_admitted_only_for_a_matching_title(tmp_path):
    cache = Cache(tmp_path)
    cache.put(s2_key("Some Paper"), {"data": [{"title": "Some Paper", "abstract": "Text."}]})
    cache.put(s2_key("Other Paper"), {"data": [{"title": "Unrelated", "abstract": "Text."}]})
    resolver = SemanticScholarResolver(cache)
    assert [c.value for c in resolver.abstract("Some Paper")] == ["Text."]
    assert resolver.abstract("Other Paper") == []


def test_s2_with_no_abstract_claims_nothing(tmp_path):
    cache = Cache(tmp_path)
    cache.put(s2_key("Some Paper"), {"data": [{"title": "Some Paper", "abstract": None}]})
    assert SemanticScholarResolver(cache).abstract("Some Paper") == []


class FailingPages:
    def resolve(self, title, urls):
        raise HttpError("503 from proceedings")


class Pages:
    def __init__(self):
        self.calls = 0

    def resolve(self, title, urls):
        from scholarmend.models import Claim

        self.calls += 1
        return [Claim(field="abstract", value="Recovered.", source="proceedings_page",
                      tier=2, confidence=0.99, evidence="e")]


def test_abstract_recovery_is_opt_in():
    pages = Pages()
    record = parse_file(FIXTURE)[0]
    resolve_record(record, proceedings_page=pages)
    assert pages.calls == 0
    ledger = resolve_record(record, proceedings_page=pages, abstracts=True)
    assert ledger.resolve("abstract").value == "Recovered."


def test_a_failed_abstract_lookup_keeps_the_venue_and_reports_the_error():
    """The failure mode this step exists to avoid: losing tier-1 work."""
    errors = []
    record = parse_file(FIXTURE)[0]
    ledger = resolve_record(record, proceedings_page=FailingPages(), abstracts=True,
                            on_error=errors.append)
    assert ledger.resolve("venue").value == "NeurIPS"
    assert len(errors) == 1


def test_the_first_source_to_answer_stops_the_escalation():
    class Spy:
        calls = 0

        def abstract(self, title):
            Spy.calls += 1
            return []

    raw = "TY  - JOUR\nTI  - X\nUR  - " + HASH + "\nER  - \n"
    record = Record(raw=raw, fields={"TI": ["X"], "UR": [HASH]}, source_file="s.ris")
    resolve_record(record, proceedings_page=Pages(), semanticscholar=Spy(), abstracts=True)
    assert Spy.calls == 0


def test_the_cli_accepts_a_single_file_and_leaves_its_siblings_out(tmp_path):
    from scholarmend.cli import main

    source = tmp_path / "in"
    source.mkdir()
    (source / "clean.ris").write_text(FIXTURE.read_text(encoding="utf-8-sig"),
                                      encoding="utf-8-sig")
    (source / "removed.ris").write_text(FIXTURE.read_text(encoding="utf-8-sig"),
                                        encoding="utf-8-sig")
    out = tmp_path / "out"
    main(["--input", str(source / "clean.ris"), "--out", str(out),
          "--cache", str(tmp_path / "cache"), "--offline"])
    expected = len(parse_file(FIXTURE))
    assert (out / "report.txt").read_text().startswith(f"records: {expected}\n")


def test_a_title_opening_with_tex_still_matches_scholars_stripped_title(tmp_path):
    page = PAGE.replace("AgentAuditor: Human-Level", "$R^2$-Guard: Human-Level")
    cache = Cache(tmp_path)
    cache.put(page_key(HASH), extract(page))
    claims = ProceedingsPageResolver(cache).resolve(
        "-Guard: Human-Level Safety & Security Evaluation", [HASH])
    assert [c.source for c in claims] == ["proceedings_page"]


def test_a_double_escaped_page_yields_plain_ampersands(tmp_path):
    page = PAGE.replace("Second paragraph.", "Caption &amp;amp; tuning, R&amp;D.")
    cache = Cache(tmp_path)
    cache.put(page_key(HASH), extract(page))
    [claim] = ProceedingsPageResolver(cache).resolve(
        "AgentAuditor: Human-Level Safety & Security Evaluation", [HASH])
    assert claim.value.endswith("Caption & tuning, R&D.")
