import agents


class FakeResp:
    text = ('<a rel="nofollow" class="result__a" href="x">Best <b>Free</b> Tools &amp; More</a>'
            '<a class="result__snippet" href="x">Wave is <b>free</b>.</a>')

    def raise_for_status(self):
        pass


async def test_search_parses_titles_and_snippets(monkeypatch):
    monkeypatch.setattr(agents.requests, "post", lambda *a, **k: FakeResp())
    assert await agents.SearchAgent().run("q") == "Best Free Tools & More: Wave is free."


async def test_search_with_no_results(monkeypatch):
    empty = FakeResp()
    empty.text = "<html></html>"
    monkeypatch.setattr(agents.requests, "post", lambda *a, **k: empty)
    assert await agents.SearchAgent().run("q") == "No results found."
