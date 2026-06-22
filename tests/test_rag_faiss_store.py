import numpy as np

from deepresearch_agent.rag.faiss_store import FaissVectorStore


def _unit(values):
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def test_faiss_store_returns_nearest_ids_by_inner_product():
    store = FaissVectorStore(dimension=2)
    store.add([10, 20], np.array([_unit([1, 0]), _unit([0, 1])], dtype=np.float32))

    results = store.search(_unit([1, 0]), k=2)

    assert results[0][0] == 10
    assert results[0][1] > 0.99
    assert {chunk_id for chunk_id, _ in results} == {10, 20}


def test_faiss_store_save_and_load_roundtrip(tmp_path):
    store = FaissVectorStore(dimension=2)
    store.add([7], np.array([_unit([1, 1])], dtype=np.float32))
    path = tmp_path / "index.faiss"
    store.save(path)

    loaded = FaissVectorStore.load(path, dimension=2)

    assert loaded.search(_unit([1, 1]), k=1)[0][0] == 7
