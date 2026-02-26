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

# Professional logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

# ==========================================
# 1. Define the Agent State and Data Models
# ==========================================
class AgentState(TypedDict):
    question: str
    metadata_filter: dict  # E.g., {"source": "RBI_Circular.pdf"}
    context: List[Document]
    answer: str
    retries: int
    is_hallucination: bool

class CritiqueOutput(BaseModel):
    """Binary score for hallucination check."""
    is_hallucination: bool = Field(
        description="True if the answer contains information NOT present in the context, False if it is perfectly grounded."
    )

# ==========================================
# 2. The Agent Class (The Brain)
# ==========================================
class SecureDocAgent:
    def __init__(self, db_dir: str = "vector_db"):
        self.db_dir = db_dir
        self.max_retries = 2
        
        # Verify Database exists
        if not os.path.exists(self.db_dir):
            raise FileNotFoundError(f"Database directory '{self.db_dir}' not found. Run ingestion.py first.")

        # Initialize core components
        logger.info("Initializing Agentic components...")
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        self.vectorstore = Chroma(persist_directory=self.db_dir, embedding_function=self.embeddings)
        
        # Use a highly capable model for generation and evaluation
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        self.eval_llm = self.llm.with_structured_output(CritiqueOutput)

        # Build the LangGraph Workflow
        self.workflow = self._build_graph()

    # --- NODE FUNCTIONS ---
    
    def retrieve_node(self, state: AgentState):
        """Step 1: Retrieve documents strictly matching the metadata filter."""
        logger.info("NODE: Retrieving context...")
        question = state["question"]
        filters = state.get("metadata_filter", {})
        
        # Use similarity search with optional metadata filtering (e.g., Client Name or Doc Type)
        docs = self.vectorstore.similarity_search(
            query=question,
            k=5,
            filter=filters if filters else None
        )
        return {"context": docs}

    def generate_node(self, state: AgentState):
        """Step 2: Generate an answer using ONLY the retrieved context."""
        logger.info(f"NODE: Generating answer (Attempt {state.get('retries', 0) + 1})...")
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a precise legal and financial assistant. Answer the user's question using ONLY the provided context. If the context does not contain the answer, say 'I cannot find the answer in the provided documents.' Do not guess."),
            ("human", "Context:\n{context}\n\nQuestion: {question}")
        ])
        
        # Format context for the prompt
        formatted_context = "\n\n".join(
            [f"[Page {doc.metadata.get('page', 'Unknown')}] {doc.page_content}" for doc in state["context"]]
        )
        
        chain = prompt | self.llm
        response = chain.invoke({"context": formatted_context, "question": state["question"]})
        
        return {"answer": response.content, "retries": state.get("retries", 0) + 1}

    def evaluate_node(self, state: AgentState):
        """Step 3: The Self-Correction mechanism. Check for hallucinations."""
        logger.info("NODE: Evaluating generated answer against source context...")
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a strict grader. Read the Context and the Answer. If the Answer contains ANY facts, numbers, or claims not explicitly stated in the Context, mark it as a hallucination (True). Otherwise, mark it False."),
            ("human", "Context: {context}\n\nAnswer: {answer}")
        ])
        
        formatted_context = "\n".join([doc.page_content for doc in state["context"]])
        
        chain = prompt | self.eval_llm
        critique = chain.invoke({"context": formatted_context, "answer": state["answer"]})
        
        logger.info(f"EVALUATION: Hallucination detected = {critique.is_hallucination}")
        return {"is_hallucination": critique.is_hallucination}

    # --- GRAPH ROUTING ---

    def route_evaluation(self, state: AgentState):
        """Decide whether to return to the user or rewrite the answer."""
        if not state["is_hallucination"]:
            logger.info("ROUTING: Answer is grounded. Sending to user.")
            return END
        elif state["retries"] >= self.max_retries:
            logger.warning("ROUTING: Max retries reached. Returning safe fallback.")
            return "fallback"
        else:
            logger.info("ROUTING: Hallucination detected. Forcing regeneration.")
            return "generate"

    def fallback_node(self, state: AgentState):
        """Provides a safe response if the agent repeatedly hallucinates."""
        return {"answer": "After reviewing the documents, I cannot provide a completely verified answer to this question based solely on the text provided."}

    # --- GRAPH COMPILATION ---

    def _build_graph(self):
        """Compiles the StateGraph."""
        workflow = StateGraph(AgentState)
        
        workflow.add_node("retrieve", self.retrieve_node)
        workflow.add_node("generate", self.generate_node)
        workflow.add_node("evaluate", self.evaluate_node)
        workflow.add_node("fallback", self.fallback_node)
        
        workflow.set_entry_point("retrieve")
        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", "evaluate")
        
        workflow.add_conditional_edges(
            "evaluate",
            self.route_evaluation,
            {
                END: END,
                "generate": "generate",
                "fallback": "fallback"
            }
        )
        workflow.add_edge("fallback", END)
        
        return workflow.compile()

    def query(self, question: str, metadata_filter: dict = None) -> dict:
        """The public method to call the agent."""
        initial_state = {
            "question": question,
            "metadata_filter": metadata_filter or {},
            "retries": 0
        }
        
        # Run the graph
        final_state = self.workflow.invoke(initial_state)
        
        # Extract unique source citations
        citations = []
        for doc in final_state["context"]:
            source = doc.metadata.get("source", "Unknown")
            page = doc.metadata.get("page", "Unknown")
            citation = f"{source} (Page {page})"
            if citation not in citations:
                citations.append(citation)
                
        return {
            "answer": final_state["answer"],
            "citations": citations
        }

if __name__ == "__main__":
    try:
        agent = SecureDocAgent()
        
        print("\n--- SECURE DOC-INTELLIGENCE AGENT (2026 Build) ---")
        
        # Example 1: General Query
        q1 = "What are the rules regarding the cooling off period?"
        print(f"\nUser: {q1}")
        result = agent.query(q1)
        print(f"\nAI: {result['answer']}")
        print(f"Sources: {', '.join(result['citations'])}")

        # Example 2: Strict Metadata Filtering (Ensuring cases don't mix)
        # Uncomment and modify the filename to match a specific PDF in your database
        """
        q2 = "Who is responsible for the external repairs?"
        print(f"\nUser: {q2} [Filtered to Lease Agreement only]")
        result = agent.query(
            question=q2, 
            metadata_filter={"source": "1525784382619_AGREEMENT.pdf"} # Strict filtering!
        )
        print(f"\nAI: {result['answer']}")
        print(f"Sources: {', '.join(result['citations'])}")
        """
        
    except Exception as e:
        logger.error(f"Agent execution failed: {e}")