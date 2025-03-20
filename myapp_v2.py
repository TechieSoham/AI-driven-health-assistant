//pip install mysql-connector-python faiss-cpu sentence-transformers

import streamlit as st
from langchain_ollama import ChatOllama
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    AIMessagePromptTemplate,
    ChatPromptTemplate
)
import mysql.connector
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

# Custom CSS styling
st.markdown("""
<style>
    /* Existing styles */
    .main {
        background-color: #1a1a1a;
        color: #ffffff;
    }
    .sidebar .sidebar-content {
        background-color: #2d2d2d;
    }
    .stTextInput textarea {
        color: #ffffff !important;
    }
    
    /* Add these new styles for select box */
    .stSelectbox div[data-baseweb="select"] {
        color: white !important;
        background-color: #3d3d3d !important;
    }
    
    .stSelectbox svg {
        fill: white !important;
    }
    
    .stSelectbox option {
        background-color: #2d2d2d !important;
        color: white !important;
    }
    
    /* For dropdown menu items */
    div[role="listbox"] div {
        background-color: #2d2d2d !important;
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)
st.title("🧠 Health Companion")
st.caption("🚀 Your Health & Wellbeing expert")


# Load embedding model
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

# Connect to MySQL Database
conn = mysql.connector.connect(
    host="your_host",
    user="your_user",
    password="your_password",
    database="your_database"
)
cursor = conn.cursor()

# Create Table for Chat Logs
cursor.execute('''CREATE TABLE IF NOT EXISTS patient_interactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id INT,
    message TEXT,
    response TEXT,
    embedding BLOB,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')
conn.commit()

# FAISS Index
embedding_dim = 384  # Dimension of MiniLM embeddings
faiss_index = faiss.IndexFlatL2(embedding_dim)

# Streamlit UI
st.title("🧠 Soham Health Companion")
st.caption("🚀 Your Health & Wellbeing expert")

# Sidebar Model Selection
with st.sidebar:
    selected_model = st.selectbox("Choose Model", ["deepseek-r1:1.5b", "deepseek-r1:3b"], index=0)

# Chat Engine
llm_engine = ChatOllama(model=selected_model, base_url="http://localhost:11434", temperature=0.3)

# System Prompt
system_prompt = SystemMessagePromptTemplate.from_template(
    "You are a highly knowledgeable and professional doctor chatbot with advanced clinical expertise in the Indian medical system. "
    "Your role is to provide detailed, evidence-based medical consultations and advice aligned with Indian medical guidelines and practices. "
    "provide interactive and responnsive answers to patient queries, and always encourage users to seek professional medical help when needed. "
    "provide remedies or medicine"
    "Answer only health-related queries within the context of Indian healthcare. If a user asks about topics outside of medicine, "
    "politely inform them that you specialize exclusively in Indian medical care. "
)

# Session State
if "message_log" not in st.session_state:
    st.session_state.message_log = []

# Function: Store Chat in MySQL + FAISS

def save_interaction(patient_id, message, response):
    embedding = embedding_model.encode(message).astype(np.float32)
    faiss_index.add(np.array([embedding]))
    cursor.execute("INSERT INTO patient_interactions (patient_id, message, response, embedding) VALUES (%s, %s, %s, %s)",
                   (patient_id, message, response, embedding.tobytes()))
    conn.commit()

# Function: Retrieve Similar Conversations

def retrieve_similar_messages(user_query, top_k=3):
    query_embedding = embedding_model.encode(user_query).astype(np.float32).reshape(1, -1)
    D, I = faiss_index.search(query_embedding, top_k)
    similar_messages = []
    for idx in I[0]:
        cursor.execute("SELECT message FROM patient_interactions WHERE id = %s", (idx+1,))
        result = cursor.fetchone()
        if result:
            similar_messages.append(result[0])
    return "\n".join(similar_messages)

# Chat Processing
user_query = st.chat_input("Ask your health question...")

if user_query:
    similar_context = retrieve_similar_messages(user_query)
    prompt_chain = ChatPromptTemplate.from_messages([
        system_prompt,
        HumanMessagePromptTemplate.from_template(similar_context + "\n" + user_query)
    ])
    ai_response = llm_engine | prompt_chain | StrOutputParser()
    save_interaction(1, user_query, ai_response)  # Storing interaction
    st.session_state.message_log.append({"role": "user", "content": user_query})
    st.session_state.message_log.append({"role": "ai", "content": ai_response})
    st.rerun()
