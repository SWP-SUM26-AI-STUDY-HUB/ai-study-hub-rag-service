import logging
from langchain.retrievers import EnsembleRetriever
from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_core.callbacks.manager import CallbackManagerForRetrieverRun

from app.pipeline.dependencies import retriever, state

logger = logging.getLogger(__name__)

def retrieve_documents(query: str):
    """
    Executes the advanced retrieval phase combining Multi-Query generation
    and Hybrid Search (BM25 + Dense Parent/Child).
    """
    bm25_retriever = state.bm25_retriever

    if not bm25_retriever:
        raise ValueError("No documents have been indexed yet. BM25Retriever is empty.")

    # --- A. Hybrid Search (Ensemble Retriever) ---
    # Combine the sparse (keyword) and dense (semantic) retrievers.
    # Weights: 30% importance to exact keyword match, 70% to semantic meaning.
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, retriever],
        weights=[0.3, 0.7]
    )

    # --- B. Multi-Query Generation ---
    # We use Google Gemini to generate multiple perspectives of the original query.
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0)
    
    # Initialize the MultiQueryRetriever
    mq_retriever = MultiQueryRetriever.from_llm(
        retriever=ensemble_retriever,
        llm=llm
    )

    # --- C. Cross-Encoder Re-ranking (Bottom of Funnel) ---
    # We use AITeamVN/Vietnamese_Reranker to meticulously score the top documents.
    # It will only return the top 5 most relevant documents.
    cross_encoder_model = HuggingFaceCrossEncoder(model_name="AITeamVN/Vietnamese_Reranker")
    compressor = CrossEncoderReranker(model=cross_encoder_model, top_n=5)
    
    # Wrap the MultiQueryRetriever with the CompressionRetriever
    compression_retriever = ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=mq_retriever
    )

    # --- D. Execution & Extraction ---
    # Extract the generated queries first for the API response.
    try:
        run_manager = CallbackManagerForRetrieverRun.get_noop_manager()
        generated_queries = mq_retriever.generate_queries(query, run_manager)
    except Exception as e:
        logger.warning(f"Failed to extract generated queries cleanly: {e}")
        generated_queries = []

    # Now, run the entire funnel!
    # Original Query -> Gemini (3 queries) -> BM25 + Dense (k=25 each) -> Deduplicate -> Cross-Encoder -> Top 5
    logger.info("Executing Full Funnel: Multi-Query -> Hybrid Search -> Cross-Encoder Re-ranking...")
    retrieved_docs = compression_retriever.invoke(query)

    # Format output for the API response
    results = []
    for d in retrieved_docs:
        results.append({
            "content": d.page_content,
            "metadata": d.metadata
        })

    return {
        "original_query": query,
        "generated_queries": generated_queries,
        "documents": results
    }
