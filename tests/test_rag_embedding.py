import numpy as np

from deepresearch_agent.rag.embedding import FakeEmbedder


def test_fake_embedder_is_deterministic_and_normalized():
    embedder = FakeEmbedder()
    docs = embedder.embed_documents(["工业设备制造", "工业设备销售"])
    assert docs.shape == (2, 8)
    assert docs.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(docs, axis=1), [1.0, 1.0], rtol=1e-5)
    again = embedder.embed_documents(["工业设备制造"])
    np.testing.assert_allclose(docs[0], again[0], rtol=1e-6)


def test_fake_embedder_query_matches_same_document_text():
    embedder = FakeEmbedder()
    query = embedder.embed_query("工业设备制造")
    doc = embedder.embed_documents(["工业设备制造"])[0]
    assert float(query @ doc) > 0.999
