import streamlit as st
import pandas as pd
from langchain_ollama import ChatOllama
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    AIMessagePromptTemplate,
    ChatPromptTemplate
)

# Load patient dataset
@st.cache_data
def load_data():
    return pd.read_csv("C:/Users/Asus/Downloads/patient_data.csv")  # Ensure your dataset file exists

df = load_data()

# Custom CSS styling
st.markdown("""
<style>
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
</style>
""", unsafe_allow_html=True)

st.title("🩺 AI Health Assistant")
st.caption("🚀 Personalized Health Insights based on Patient Data")

# Sidebar for configuration
with st.sidebar:
    st.header("⚙ Configuration")
    selected_model = st.selectbox(
        "Choose Model",
        ["deepseek-r1:1.5b", "deepseek-r1:3b"],
        index=0
    )
    st.divider()
    st.markdown("### Model Capabilities")
    st.markdown("""
    - 🏥 Medical Advice (General)
    - 📝 Patient-Specific Insights
    - 📊 Data-Driven Health Predictions
    """)
    st.divider()
    st.markdown("Built with [Ollama](https://ollama.ai/) | [LangChain](https://python.langchain.com/)")

# Patient Login Section
st.subheader("🔐 Patient Login")
patient_id = st.text_input("Enter your Patient ID", key="patient_id")

if patient_id:
    # Fetch patient details
    patient_info = df[df["patient_id"] == int(patient_id)] if patient_id.isnumeric() else None

    if patient_info is not None and not patient_info.empty:
        patient_data = patient_info.iloc[0]  # Extract first matching row
        st.success(f"✅ Welcome, {patient_data['name']}!")

        # Display patient details
        st.markdown(f"""
        *🆔 Patient ID:* {patient_data['patient_id']}  
        *👤 Name:* {patient_data['name']}  
        *🎂 Age:* {patient_data['age']}  
        *🩸 Blood Group:* {patient_data['blood-group']}  
        *⚧ Gender:* {patient_data['gender']}  
        *📜 Medical History:* {patient_data['past-history']}  
        """)

        # Initiate Chatbot after successful login
        st.divider()
        st.subheader("💬 Chat with AI Health Assistant")

        # Initiate chatbot engine
        llm_engine = ChatOllama(
            model=selected_model,
            base_url="http://localhost:11434",
            temperature=0.3
        )

        # System prompt configuration
        system_prompt = SystemMessagePromptTemplate.from_template(
            f"You are an AI health assistant. The patient details are: "
            f"Name: {patient_data['name']}, Age: {patient_data['age']}, Blood Group: {patient_data['blood-group']}, "
            f"Gender: {patient_data['gender']}, Medical History: {patient_data['past-history']}. "
            "Provide relevant medical advice based on the patient's information."
        )

        # Session state management
        if "message_log" not in st.session_state:
            st.session_state.message_log = [{"role": "ai", "content": "Hi! How can I assist with your health concerns today? 🏥"}]

        # Display chat messages
        chat_container = st.container()
        with chat_container:
            for message in st.session_state.message_log:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        # Chat input
        user_query = st.chat_input("Ask about your health...")

        def generate_ai_response(prompt_chain):
            processing_pipeline = prompt_chain | llm_engine | StrOutputParser()
            return processing_pipeline.invoke({})

        def build_prompt_chain():
            prompt_sequence = [system_prompt]
            for msg in st.session_state.message_log:
                if msg["role"] == "user":
                    prompt_sequence.append(HumanMessagePromptTemplate.from_template(msg["content"]))
                elif msg["role"] == "ai":
                    prompt_sequence.append(AIMessagePromptTemplate.from_template(msg["content"]))
            return ChatPromptTemplate.from_messages(prompt_sequence)

        if user_query:
            st.session_state.message_log.append({"role": "user", "content": user_query})
            
            # Generate AI response
            with st.spinner("🩺 Processing your health query..."):
                prompt_chain = build_prompt_chain()
                ai_response = generate_ai_response(prompt_chain)

                # Remove the <think> section from the response
                if "<think>" in ai_response and "</think>" in ai_response:
                    ai_response = ai_response.split("</think>")[-1].strip()
            
            st.session_state.message_log.append({"role": "ai", "content": ai_response})
            st.rerun()

    else:
        st.error("❌ Invalid Patient ID. Please try again.")