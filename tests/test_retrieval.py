from store.catalog import chunk_article
from store.retrieval import BM25Index, tokenize


def test_tokenize_drops_stopwords_and_folds_plurals():
    assert tokenize("What are the Returns windows?") == ["return", "window"]


def test_bm25_ranks_relevant_doc_first_and_drops_zero_scores():
    index = BM25Index(["red wool sweater", "cast iron skillet", "wool socks and wool hat"])
    hits = index.search("wool", 5)
    assert [i for i, _ in hits] == [2, 0]  # doc 1 has no match and is excluded
    assert index.search("unicorn", 5) == []


def test_chunk_article_splits_on_h2():
    chunks = chunk_article("doc", "# Title\n\n## One\nalpha\n\n## Two\nbeta\ngamma\n")
    assert [(c.chunk_id, c.section, c.text) for c in chunks] == [
        ("doc#1", "One", "alpha"), ("doc#2", "Two", "beta gamma")]
    assert all(c.title == "Title" for c in chunks)


def test_help_center_search_returns_expected_docs(catalog):
    assert catalog.search_help("how long does shipping take", 3)[0].doc_id == "shipping"
    assert catalog.search_help("can I return a final sale item", 3)[0].doc_id == "returns-policy"


def test_catalog_sizes(catalog):
    assert len(catalog.products) == 25
    assert len(catalog.orders) == 30
    assert len({c.doc_id for c in catalog.chunks}) == 8
