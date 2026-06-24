import logging
from typing import List, Dict
from app.core.clients import llm
from app.core.performance import stage
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger(__name__)

def generate_rag_response(query: str, documents: List[Dict]) -> str:
    """
    Generates a final answer using the retrieved documents as context.
    """
    try:
        # Build the LLM context. Each retrieved snippet is labelled with a stable
        # numeric citation [N] (1-based) so the model can reference its sources with a
        # compact marker that maps 1:1 to the citation list returned to the client.
        # The retrieval layer prepends a verbose "[Title: ..., Document ID: ...]\n" tag
        # to each content blob; drop it here and relabel the snippet with [N]. The order
        # of `documents` is identical to debug.documents, so [N] <-> citations[N-1].
        context_parts = []
        for idx, doc in enumerate(documents, start=1):
            content = doc.get("content", "")
            context_parts.append("[{}]\n{}".format(idx, _strip_citation_prefix(content)))
        context_text = "\n\n---\n\n".join(context_parts)
        # Define the System Prompt via PromptTemplate. The model must emit only the
        # compact numeric source tags [N] that prefix each snippet.
        system_template = """You are an intelligent AI assistant. Your task is to answer the question based on the provided context documents.

MANDATORY REQUIREMENTS:
1. You must automatically detect the language of the question (query) and answer in THAT exact language.
2. Every context snippet below is labelled with a numeric source tag in square brackets, e.g. [1], [2], [3]. These numbers are the ONLY valid citation markers.
3. Whenever you state information drawn from the context, append the corresponding source tag(s) at the end of that sentence or paragraph, e.g. "... [1]" or "... [1][2]". You may group several sources together.
4. Use ONLY the numbers that actually label a snippet. Never invent, guess, or omit a number, and never output verbose citations such as titles, file names, or document IDs.
5. Absolutely do not fabricate information. If the context does not contain enough information to answer the question, clearly state that there is no information in the documents.

Context:
{context}

Question:
{query}

Answer:"""

        prompt = PromptTemplate.from_template(system_template)
        
        # S2: shared singleton LLM
        chain = prompt | llm

        logger.info(f"Generating RAG response for query: {query}")
        with stage("generation"):
            response = chain.invoke({
                "context": context_text,
                "query": query
            })
        
        return response.content.strip()

    except Exception as e:
        logger.error(f"Error during RAG response generation: {e}")
        return "An error occurred while generating the answer. Please try again later."


def _strip_citation_prefix(content: str) -> str:
    """Drops the verbose "[...]\\n" citation tag that retrieval prepends to each chunk,
    leaving only the raw snippet body for the LLM context."""
    if not content:
        return ""
    newline = content.find("\n")
    if content.startswith("[") and 0 < newline < 200:
        return content[newline + 1:]
    return content
