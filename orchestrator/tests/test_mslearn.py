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
