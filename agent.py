import os
import logging
from typing import List, Dict, Any, TypedDict
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from langgraph.graph import StateGraph, END

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

# ==========================================
# 1. State and Data Models
# ==========================================
class AgentState(TypedDict):
    question: str
    metadata_filter: dict
    target_db: str  # 'local', 'global', or 'both'
    context: List[Document]
    answer: str
    retries: int
    is_hallucination: bool

class CritiqueOutput(BaseModel):
    is_hallucination: bool = Field(description="True if hallucinated, False if perfectly grounded.")

class RouterOutput(BaseModel):
    target_db: str = Field(description="Must be 'local', 'global', or 'both'.")

# ==========================================
# 2. The Agent Class
# ==========================================
class SecureDocAgent:
    def __init__(self, db_dir: str = "vector_db", global_db_dir: str = "global_vector_db"):
        self.db_dir = db_dir
        self.global_db_dir = global_db_dir
        self.max_retries = 2
        
        logger.info("Initializing Agentic components...")
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        
        # Initialize Local DB
        if not os.path.exists(self.db_dir):
            os.makedirs(self.db_dir, exist_ok=True)
        self.local_vectorstore = Chroma(persist_directory=self.db_dir, embedding_function=self.embeddings)
        
        # Initialize Global DB
        if not os.path.exists(self.global_db_dir):
            os.makedirs(self.global_db_dir, exist_ok=True)
        self.global_vectorstore = Chroma(persist_directory=self.global_db_dir, embedding_function=self.embeddings)
        
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        self.eval_llm = self.llm.with_structured_output(CritiqueOutput)
        self.router_llm = self.llm.with_structured_output(RouterOutput)

        self.workflow = self._build_graph()

    # --- NODE FUNCTIONS ---
    def route_query_node(self, state: AgentState):
        """Determines which database to query."""
        logger.info("NODE: Routing query...")
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Analyze the query. If it asks about specific uploaded files/contracts, output 'local'. If it asks about general law/RBI/GST, output 'global'. If it requires comparing a contract to law, output 'both'."),
            ("human", "{question}")
        ])
        decision = (prompt | self.router_llm).invoke({"question": state["question"]})
        return {"target_db": decision.target_db}

    def retrieve_node(self, state: AgentState):
        """Retrieves documents from the appropriate vectorstore."""
        logger.info("NODE: Retrieving context...")
        question = state["question"]
        filters = state.get("metadata_filter")
        target = state.get("target_db", "local")
        
        # PROPER FIX: ChromaDB requires explicitly None if empty, not {}
        valid_filter = filters if filters else None

        docs = []
        if target in ["local", "both"]:
            try:
                docs.extend(self.local_vectorstore.similarity_search(query=question, k=5, filter=valid_filter))
            except Exception as e:
                logger.error(f"Local retrieval failed: {e}")
                
        if target in ["global", "both"]:
            try:
                # We don't apply user metadata filters to the global regulation DB
                docs.extend(self.global_vectorstore.similarity_search(query=question, k=3))
            except Exception as e:
                logger.error(f"Global retrieval failed: {e}")

        return {"context": docs}

    def generate_node(self, state: AgentState):
        logger.info(f"NODE: Generating answer (Attempt {state.get('retries', 0) + 1})...")
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a precise legal assistant. Answer using ONLY the provided context. If not found, say 'I cannot find the answer.'"),
            ("human", "Context:\n{context}\n\nQuestion: {question}")
        ])
        
        formatted_context = "\n\n".join([f"[Page {doc.metadata.get('page', 'Unknown')}] {doc.page_content}" for doc in state.get("context", [])])
        response = (prompt | self.llm).invoke({"context": formatted_context, "question": state["question"]})
        
        return {"answer": response.content, "retries": state.get("retries", 0) + 1}

    def evaluate_node(self, state: AgentState):
        logger.info("NODE: Evaluating generated answer for hallucinations...")
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Read Context and Answer. If the Answer contains ANY facts not in the Context, mark hallucination as True. Otherwise False."),
            ("human", "Context: {context}\n\nAnswer: {answer}")
        ])
        
        formatted_context = "\n".join([doc.page_content for doc in state.get("context", [])])
        critique = (prompt | self.eval_llm).invoke({"context": formatted_context, "answer": state["answer"]})
        
        return {"is_hallucination": critique.is_hallucination}

    def fallback_node(self, state: AgentState):
        return {"answer": "After reviewing the documents, I cannot provide a completely verified answer to this question based solely on the text provided."}

    # --- GRAPH ROUTING & COMPILATION ---
    def route_evaluation(self, state: AgentState):
        if not state["is_hallucination"]:
            return END
        elif state["retries"] >= self.max_retries:
            return "fallback"
        else:
            return "generate"

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        
        workflow.add_node("route", self.route_query_node)
        workflow.add_node("retrieve", self.retrieve_node)
        workflow.add_node("generate", self.generate_node)
        workflow.add_node("evaluate", self.evaluate_node)
        workflow.add_node("fallback", self.fallback_node)
        
        workflow.set_entry_point("route")
        workflow.add_edge("route", "retrieve")
        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", "evaluate")
        
        workflow.add_conditional_edges(
            "evaluate",
            self.route_evaluation,
            {END: END, "generate": "generate", "fallback": "fallback"}
        )
        workflow.add_edge("fallback", END)
        
        return workflow.compile()

    def query(self, question: str, metadata_filter: dict = None) -> dict:
        """The public entrypoint."""
        initial_state = {
            "question": question,
            "metadata_filter": metadata_filter, # Passed directly, no `or {}`
            "retries": 0
        }
        
        final_state = self.workflow.invoke(initial_state)
        
        citations = []
        for doc in final_state.get("context", []):
            source = doc.metadata.get("source", "Unknown")
            page = doc.metadata.get("page", "Unknown")
            citation = f"{source} (Page {page})"
            if citation not in citations:
                citations.append(citation)
                
        return {
            "answer": final_state.get("answer", "System Error"),
            "citations": citations
        }