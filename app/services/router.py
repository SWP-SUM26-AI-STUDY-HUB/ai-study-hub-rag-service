import logging
from typing import Optional
from app.core.clients import llm
from app.core.performance import stage
from langchain_core.prompts import PromptTemplate

from app.services.retrieval import retrieve_documents
from app.database.document_store import get_document_summary, get_user_document_ids

logger = logging.getLogger(__name__)

def route_chat_request(query: str, user_id: str, document_id: Optional[str] = None) -> dict:
    """
    Routes the user query to either the SUMMARY branch or the QA (retrieval) branch using an LLM.
    Uses user_id to fetch the scope of documents if document_id is not explicitly provided.
    """
    # Build a list of valid document_ids
    document_ids = []
    if document_id:
        # If there is a specific document
        document_ids = [document_id]
    else:
        # If QA is intended for all user documents
        with stage("user_doc_ids"):
            document_ids = get_user_document_ids(user_id)
        if not document_ids:
            return {
                "type": "error",
                "message": "No documents found belonging to this user."
            }

    # 1. Define classification prompt
    system_instruction = (
        "You are a question classification system. Based on the question below, decide whether the user wants to: "
        "1. View the general overview or summary of a specific document (Return 'SUMMARY'). "
        "2. Search for documents based on a topic/description, find specific information, or ask Q&A about the content (Return 'QA'). "
        "ONLY RETURN EITHER SUMMARY OR QA."
    )
    
    prompt = PromptTemplate.from_template(
        "{system_instruction}\n\nQuestion: {query}"
    )

    # 2. Use LLM for classification (S2: shared singleton)
    chain = prompt | llm

    try:
        with stage("router_llm"):
            response = chain.invoke({
                "system_instruction": system_instruction,
                "query": query
            })
        decision = response.content.strip().upper()
    except Exception as e:
        logger.error(f"Error during LLM routing: {e}")
        # Default fallback to QA if there is an error generating text
        decision = "QA"

    logger.info(f"Router decision for query '{query}': {decision}")

    # 3. Execution branching
    if "SUMMARY" in decision:
        if not document_id:
            return {
                "type": "error",
                "message": "To get a summary, please select a specific document (provide document_id)."
            }
        with stage("document_summary_fetch"):
            summary_text = get_document_summary(document_id)
        return {
            "type": "summary",
            "content": summary_text
        }
    else:
        # QA on document_ids array
        retrieval_data = retrieve_documents(query, document_ids)
        return {
            "type": "qa",
            "retrieval_data": retrieval_data
        }
