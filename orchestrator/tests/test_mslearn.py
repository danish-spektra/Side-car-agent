from app.mslearn import search_learn

def test_search_learn_maps_results():
    def fake_get_json(url, params):
        assert params["search"] == "create storage account"
        return {"results": [
            {"title": "Create a storage account", "url": "https://learn.microsoft.com/x", "description": "How to."},
        ]}
    out = search_learn("create storage account", get_json=fake_get_json)
    assert out == [{"title": "Create a storage account",
                    "url": "https://learn.microsoft.com/x",
                    "summary": "How to."}]

def test_search_learn_swallows_errors():
    def boom(url, params):
        raise IOError("down")
    assert search_learn("anything", get_json=boom) == []

# --- full-article fetch for the LEARN_MORE deepening pass ---

from app.mslearn import fetch_learn_page

def test_fetch_learn_page_strips_html():
    html = ("<html><head><style>.x{}</style><script>var a;</script></head>"
            "<body><h1>Create an index</h1><p>Use the <b>portal</b> blade.</p></body></html>")
    out = fetch_learn_page("https://learn.microsoft.com/azure/search/x",
                           get_text=lambda url: html)
    assert "Create an index" in out and "Use the portal blade." in out
    assert "<" not in out and "var a" not in out and ".x{}" not in out

def test_fetch_learn_page_only_learn_domain():
    # SSRF guard: the model chooses the query, but we only ever fetch first-party docs
    assert fetch_learn_page("https://evil.example.com/a", get_text=lambda u: "x") == ""
    assert fetch_learn_page("http://learn.microsoft.com/a", get_text=lambda u: "x") == ""

def test_fetch_learn_page_caps_length():
    out = fetch_learn_page("https://learn.microsoft.com/a",
                           get_text=lambda u: "word " * 10000, max_chars=100)
    assert len(out) <= 100

def test_fetch_learn_page_swallows_errors():
    def boom(url):
        raise IOError("down")
    assert fetch_learn_page("https://learn.microsoft.com/a", get_text=boom) == ""
