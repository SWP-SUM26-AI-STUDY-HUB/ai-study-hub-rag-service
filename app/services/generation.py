import logging
from typing import List, Dict
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger(__name__)

def generate_rag_response(query: str, documents: List[Dict]) -> str:
    """
    Generates a final answer using the retrieved documents as context.
    """
    try:
        # Prepare context by joining all retrieved document contents
        # Each document already has the citation prefixed to its content
        context_parts = []
        for doc in documents:
            if "content" in doc:
                context_parts.append(doc["content"])
        
        context_text = "\n\n---\n\n".join(context_parts)

        # Define the System Prompt via PromptTemplate
        # The prompt forces the LLM to answer in the same language as the query
        # and to include the exact citations from the context.
        system_template = """You are an intelligent AI assistant. Your task is to answer the question based on the provided context documents.

MANDATORY REQUIREMENTS:
1. You must automatically detect the language of the question (query) and answer in THAT exact language.
2. All information you provide must be accompanied by a source citation. Each context snippet below has been prefixed with a Citation tag (e.g., [Title: ..., Document ID: ..., File: ..., Page: ...]).
3. When you use information from a snippet to answer, copy that exact Citation tag verbatim and insert it at the end of your sentence or paragraph. This ensures transparency of sources.
4. Absolutely do not fabricate information if it is not mentioned in the context. If the context does not contain information to answer the question, clearly state that there is no information in the document.

Context:
{context}

Question:
{query}

Answer:"""

        prompt = PromptTemplate.from_template(system_template)
        
        # Initialize LLM
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0)
        
        # Create chain and invoke
        chain = prompt | llm
        
        logger.info(f"Generating RAG response for query: {query}")
        response = chain.invoke({
            "context": context_text,
            "query": query
        })
        
        return response.content.strip()

    except Exception as e:
        logger.error(f"Error during RAG response generation: {e}")
        return "An error occurred while generating the answer. Please try again later."
