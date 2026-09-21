from __future__ import annotations

from scholarmend import miners
from scholarmend.miners import arxiv, openreview, pmlr


def value(claims, field):
    return next((c.value for c in claims if c.field == field), None)


def test_openreview_forum_url_yields_the_forum_id():
    claims = openreview.mine("https://openreview.net/forum?id=r0BFucF2dH")
    assert value(claims, "forum_id") == "r0BFucF2dH"


def test_openreview_pdf_url_yields_the_same_forum_id():
    claims = openreview.mine("https://openreview.net/pdf?id=r0BFucF2dH")
    assert value(claims, "forum_id") == "r0BFucF2dH"


def test_openreview_does_not_claim_a_version():
    # A forum id alone cannot say whether this is a workshop submission or a
    # main-track paper. Only the tier-2 venueid settles that.
    assert value(openreview.mine("https://openreview.net/forum?id=r0BFucF2dH"), "version") is None


def test_openreview_ignores_other_hosts():
    assert openreview.mine("https://arxiv.org/abs/2501.00001") == []


def test_pmlr_github_asset_url_yields_the_volume():
    url = "https://raw.githubusercontent.com/mlresearch/v318/main/assets/huang26a/huang26a.pdf"
    assert value(pmlr.mine(url), "pmlr_volume") == "318"


def test_pmlr_press_url_yields_the_volume():
    assert value(pmlr.mine("https://proceedings.mlr.press/v267/smith25a.html"), "pmlr_volume") == "267"


def test_pmlr_ignores_unrelated_github_content():
    assert pmlr.mine("https://raw.githubusercontent.com/someone/else/main/x.pdf") == []


def test_arxiv_abs_url_yields_the_id_and_marks_it_a_preprint():
    claims = arxiv.mine("https://arxiv.org/abs/2501.01234v2")
    assert value(claims, "arxiv_id") == "2501.01234"
    assert value(claims, "version") == "preprint"


def test_arxiv_pdf_url_yields_the_same_id():
    assert value(arxiv.mine("https://arxiv.org/pdf/2501.01234"), "arxiv_id") == "2501.01234"


def test_mine_all_runs_every_miner_over_every_url():
    urls = [
        (
            "https://proceedings.iclr.cc/paper_files/paper/2026/hash/"
            "635a38ee326fb0464e0c2b1c1a0b0c1d-Abstract-Conference.html"
        ),
        "https://openreview.net/forum?id=r0BFucF2dH",
    ]
    claims = miners.mine_all(urls)
    assert value(claims, "venue") == "ICLR"
    assert value(claims, "forum_id") == "r0BFucF2dH"


def test_mine_all_on_urls_no_miner_recognises_returns_nothing():
    assert miners.mine_all(["https://example.com/paper.pdf"]) == []
