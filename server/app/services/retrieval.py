from llama_index.core.schema import MetadataMode, NodeWithScore, QueryBundle
from llama_index.core.tools import RetrieverTool

from app.core.config import get_settings
from app.integrations.llamaindex_retrieval import (
    LexicalRerankPostprocessor,
    build_router_retriever,
)
from app.integrations.langfuse_tracing import (
    sanitize_citations,
    get_langfuse_tracer,
)
from app.integrations.qdrant_store import QdrantChunkStore
from app.services.retrieval_ranking import (
    compute_retrieval_score,
    score_lexical_match,
)


class RetrievalService:
    def __init__(self, store: QdrantChunkStore | None = None) -> None:
        self.settings = get_settings()
        self.store = store or QdrantChunkStore()

    def describe_strategy(self) -> str:
        return (
            "llamaindex qdrant_vector_store + router_retriever + lexical_rerank "
            f"(embedding={self.store.embedding_service.active_backend_name})"
        )

    def _candidate_limit(self, top_k: int) -> int:
        factor = max(1, self.settings.retrieval_overfetch_factor)
        return max(top_k, top_k * factor)

    def _rerank_nodes(
        self,
        *,
        query: str,
        nodes: list[NodeWithScore],
        top_k: int,
    ) -> list[NodeWithScore]:
        span = get_langfuse_tracer().start_rerank_span(
            input={"query": query},
            metadata={
                "top_k": top_k,
                "candidate_count": len(nodes),
                "retrieval_dense_weight": self.settings.retrieval_dense_weight,
                "retrieval_lexical_weight": self.settings.retrieval_lexical_weight,
                "before_top_chunks": self._snapshot_nodes(
                    query=query,
                    nodes=nodes,
                    limit=top_k,
                    sort_mode="vector",
                ),
            },
        )
        postprocessor = LexicalRerankPostprocessor(top_k=top_k)
        try:
            reranked = postprocessor.postprocess_nodes(
                nodes,
                query_bundle=QueryBundle(query_str=query),
            )
            span.end(
                output={
                    "after_top_chunks": self._snapshot_nodes(
                        query=query,
                        nodes=reranked,
                        limit=top_k,
                        sort_mode="final",
                    )
                },
                metadata={
                    "reranked_count": len(reranked),
                },
            )
            return reranked
        except Exception as exc:
            span.end(level="ERROR", status_message=str(exc))
            raise

    def _node_to_hit(self, item: NodeWithScore) -> dict:
        metadata = dict(item.node.metadata or {})
        return {
            "chunk_id": str(metadata.get("chunk_id", item.node.node_id)),
            "document_id": str(metadata.get("document_id", "")),
            "knowledge_base_id": str(metadata.get("knowledge_base_id", "")),
            "chunk_index": int(metadata.get("chunk_index", 0)),
            "file_name": str(metadata.get("file_name", "")),
            "content": item.node.get_content(metadata_mode=MetadataMode.NONE).strip(),
            "score": round(float(metadata.get("score", item.score or 0.0)), 6),
            "vector_score": round(
                float(metadata.get("vector_score", item.score or 0.0)),
                6,
            ),
            "lexical_score": round(float(metadata.get("lexical_score", 0.0)), 6),
            "embedding_backend": str(metadata.get("embedding_backend", "")),
        }

    def _snapshot_nodes(
        self,
        *,
        query: str,
        nodes: list[NodeWithScore],
        limit: int,
        sort_mode: str,
    ) -> list[dict]:
        snapshots = [self._node_to_rerank_snapshot(query=query, item=item) for item in nodes]
        if sort_mode == "vector":
            snapshots.sort(
                key=lambda item: (
                    -float(item["vector_score"]),
                    str(item["knowledge_base_id"]),
                    int(item["chunk_index"]),
                )
            )
        else:
            snapshots.sort(
                key=lambda item: (
                    -float(item["final_score"]),
                    -float(item["lexical_score"]),
                    -float(item["vector_score"]),
                    str(item["knowledge_base_id"]),
                    int(item["chunk_index"]),
                )
            )
        return [
            {
                **snapshot,
                "rank": index,
            }
            for index, snapshot in enumerate(snapshots[: max(0, limit)], start=1)
        ]

    def _node_to_rerank_snapshot(
        self,
        *,
        query: str,
        item: NodeWithScore,
    ) -> dict:
        metadata = dict(item.node.metadata or {})
        content = item.node.get_content(metadata_mode=MetadataMode.NONE).strip()
        vector_score = float(metadata.get("vector_score", item.score or 0.0))
        lexical_score = float(
            metadata.get(
                "lexical_score",
                score_lexical_match(
                    query,
                    content,
                    file_name=str(metadata.get("file_name", "")),
                ),
            )
        )
        final_score = float(
            metadata.get(
                "score",
                compute_retrieval_score(
                    vector_score=vector_score,
                    lexical_score=lexical_score,
                ),
            )
        )
        return {
            "chunk_id": str(metadata.get("chunk_id", item.node.node_id)),
            "document_id": str(metadata.get("document_id", "")),
            "knowledge_base_id": str(metadata.get("knowledge_base_id", "")),
            "chunk_index": int(metadata.get("chunk_index", 0)),
            "file_name": str(metadata.get("file_name", "")),
            "vector_score": round(vector_score, 6),
            "lexical_score": round(lexical_score, 6),
            "final_score": round(final_score, 6),
        }

    def retrieve(
        self,
        knowledge_base_id: str,
        query: str,
        top_k: int,
    ) -> list[dict]:
        span = get_langfuse_tracer().start_retrieval_span(
            input={"query": query},
            metadata={
                "mode": "single_kb",
                "knowledge_base_id": knowledge_base_id,
                "top_k": top_k,
                "candidate_limit": self._candidate_limit(top_k),
                "strategy": self.describe_strategy(),
                "retrieval_dense_weight": self.settings.retrieval_dense_weight,
                "retrieval_lexical_weight": self.settings.retrieval_lexical_weight,
            },
        )
        retriever = self.store.as_retriever(
            knowledge_base_id=knowledge_base_id,
            top_k=self._candidate_limit(top_k),
        )
        if retriever is None:
            span.end(output=[], metadata={"retrieval_count": 0})
            return []

        try:
            nodes = retriever.retrieve(query)
            reranked_nodes = self._rerank_nodes(query=query, nodes=nodes, top_k=top_k)
            hits = [self._node_to_hit(item) for item in reranked_nodes]
            span.end(
                output=sanitize_citations(hits),
                metadata={
                    "candidate_count": len(nodes),
                    "retrieval_count": len(hits),
                },
            )
            return hits
        except Exception as exc:
            span.end(level="ERROR", status_message=str(exc))
            raise

    def retrieve_many(
        self,
        knowledge_base_ids: list[str],
        query: str,
        top_k: int,
        per_kb_top_k: int | None = None,
    ) -> list[dict]:
        unique_kb_ids = list(dict.fromkeys(kb_id for kb_id in knowledge_base_ids if kb_id))
        if not unique_kb_ids:
            return []

        limit = per_kb_top_k or top_k
        span = get_langfuse_tracer().start_retrieval_span(
            input={"query": query},
            metadata={
                "mode": "multi_kb",
                "knowledge_base_ids": unique_kb_ids,
                "top_k": top_k,
                "per_kb_top_k": limit,
                "candidate_limit_per_kb": self._candidate_limit(limit),
                "strategy": self.describe_strategy(),
                "retrieval_dense_weight": self.settings.retrieval_dense_weight,
                "retrieval_lexical_weight": self.settings.retrieval_lexical_weight,
            },
        )
        retriever_tools: list[RetrieverTool] = []
        for knowledge_base_id in unique_kb_ids:
            retriever = self.store.as_retriever(
                knowledge_base_id=knowledge_base_id,
                top_k=self._candidate_limit(limit),
            )
            if retriever is None:
                continue
            retriever_tools.append(
                RetrieverTool.from_defaults(
                    retriever=retriever,
                    name=f"knowledge_base_{knowledge_base_id}",
                    description=f"仅检索知识库 {knowledge_base_id} 下的文档片段。",
                )
            )

        if not retriever_tools:
            span.end(output=[], metadata={"retrieval_count": 0})
            return []

        try:
            router_retriever = build_router_retriever(retriever_tools)
            nodes = router_retriever.retrieve(query)
            reranked_nodes = self._rerank_nodes(query=query, nodes=nodes, top_k=top_k)
            hits = [self._node_to_hit(item) for item in reranked_nodes]
            span.end(
                output=sanitize_citations(hits),
                metadata={
                    "candidate_count": len(nodes),
                    "retrieval_count": len(hits),
                },
            )
            return hits
        except Exception as exc:
            span.end(level="ERROR", status_message=str(exc))
            raise
