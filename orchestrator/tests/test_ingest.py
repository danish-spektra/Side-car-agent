from app.ingest import ordered_paths, extract_image_refs, resolve_ref

MASTERDOC = [{
    "Name": "Demo",
    "Files": [
        {"RawFilePath": "https://x/Labs/Exercise-1.md", "Order": 2},
        {"RawFilePath": "https://x/Labs/gettingstarted.md", "Order": 1},
    ],
}]

def test_ordered_paths_sorts_by_order():
    assert ordered_paths(MASTERDOC) == [
        "https://x/Labs/gettingstarted.md",
        "https://x/Labs/Exercise-1.md",
    ]

def test_ordered_paths_accepts_single_object():
    assert ordered_paths(MASTERDOC[0])[0] == "https://x/Labs/gettingstarted.md"

def test_extract_image_refs():
    md = "text\n![](../images/a.png)\nmore ![alt](https://cdn/b.jpg) end"
    assert extract_image_refs(md) == ["../images/a.png", "https://cdn/b.jpg"]

def test_resolve_ref_relative():
    assert (
        resolve_ref("https://docs-api.cloudlabs.ai/repos/raw.githubusercontent.com/O/R/refs/heads/main/Labs/Exercise-1.md",
                    "../images/aisnew.png")
        == "https://docs-api.cloudlabs.ai/repos/raw.githubusercontent.com/O/R/refs/heads/main/images/aisnew.png"
    )

def test_resolve_ref_absolute_passthrough():
    assert resolve_ref("https://x/Labs/e.md", "https://cdn/b.jpg") == "https://cdn/b.jpg"
