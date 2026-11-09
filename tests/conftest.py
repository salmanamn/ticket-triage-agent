import hashlib
import math
import re

import pytest


class HashEmbedder:
    """Deterministic bag-of-words hashing embedder: keyword overlap -> cosine similarity. CI-safe, no model."""

    model = "hash-bow"
    dimensions = 768

    def embed(self, texts, purpose):
        vectors = []
        for text in texts:
            v = [0.0] * self.dimensions
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                if len(token) >= 3:
                    v[int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % self.dimensions] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            vectors.append([x / norm for x in v])
        return vectors


@pytest.fixture
def hash_embedder():
    return HashEmbedder()
