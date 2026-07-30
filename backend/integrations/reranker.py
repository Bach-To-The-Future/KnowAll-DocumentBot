"""Cross-encoder reranker (fastembed / ONNX, CPU-friendly)."""
import logging
import math
import threading

from fastembed.rerank.cross_encoder import TextCrossEncoder

from core.config import Settings
from core.interfaces import Reranker

logger = logging.getLogger(__name__)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class FastembedReranker(Reranker):
    def __init__(self, settings: Settings) -> None:
        self._model_name = settings.reranker_model
        self._encoder: TextCrossEncoder | None = None
        self._lock = threading.Lock()

    def _get_encoder(self) -> TextCrossEncoder:
        if self._encoder is None:
            with self._lock:
                if self._encoder is None:
                    logger.info(f"Loading reranker model: {self._model_name}")
                    self._encoder = TextCrossEncoder(model_name=self._model_name)
        return self._encoder

    def scores(self, query: str, texts: list[str]) -> list[float]:
        # Cross-encoder outputs are logits aligned 1:1 with input order;
        # sigmoid maps them to [0, 1] so the score floor is model-friendly.
        logits = list(self._get_encoder().rerank(query, texts))
        return [_sigmoid(logit) for logit in logits]

    def warm(self) -> None:
        self._get_encoder()
