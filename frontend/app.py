import streamlit as st
import requests

# Constants
API_URL = "http://localhost:8000/api/v1/sandbox/run"

# Page Configuration
st.set_page_config(
    page_title="Agentic Sandbox | Security Matrix",
    layout="wide"
)

st.title("🛡️ Agentic Sandbox | Security Matrix")
st.markdown("Execute untrusted agent code in an isolated Docker environment with AI-intercepted network traffic.")

# Define example code snippets
EXAMPLES = {
    "Custom Code": "",
    "Benign Data Processor": '''print("Starting data processing...")
data = [1, 2, 3, 4, 5]
result = [x * 2 for x in data]
print(f"Result: {result}")
print("Data processing complete.")''',
    "Stripe API Test": '''import requests

print("Attempting to charge customer via Stripe API...")
try:
    response = requests.post(
        "https://api.stripe.com/v1/charges",
        json={"amount": 2000, "currency": "usd"}
    )
    print(f"Response Status: {response.status_code}")
    print(response.text)
except Exception as e:
    print(f"Error: {e}")''',
    "Malicious File Access": '''print("Attempting to access host filesystem...")
try:
    with open("/etc/passwd", "r") as f:
        print(f.read()[:200] + "...\\n[TRUNCATED]")
except Exception as e:
    print(f"Access Denied: {e}")'''
}

col1, col2 = st.columns(2)

with col1:
    st.subheader("Agent Code Input")
    
    selected_example = st.selectbox(
        "Load Example Agent",
        options=list(EXAMPLES.keys()),
        index=0
    )
    
    # Use session state to handle text area updates cleanly
    if "current_code" not in st.session_state:
        st.session_state.current_code = EXAMPLES["Custom Code"]
        st.session_state.last_example = "Custom Code"
        
    # If the user changes the dropdown, update the code in the text area
    if selected_example != st.session_state.last_example:
        st.session_state.current_code = EXAMPLES[selected_example]
        st.session_state.last_example = selected_example

    code_input = st.text_area(
        "Python Code",
        value=st.session_state.current_code,
        height=400,
        label_visibility="collapsed"
    )
    
    # Update session state with manual edits
    st.session_state.current_code = code_input

    run_btn = st.button("🚀 Run Security Simulation", use_container_width=True, type="primary")

with col2:
    st.subheader("Execution Results")
    
    if run_btn:
        if not code_input.strip():
            st.warning("Please enter some Python code to execute.")
        else:
            with st.spinner("Provisioning isolated container & routing matrix..."):
                try:
                    response = requests.post(
                        API_URL, 
                        json={"code": code_input},
                        timeout=35  # Slightly longer than container timeout
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        status = data.get("status", "unknown")
                        stdout = data.get("stdout", "")
                        stderr = data.get("stderr", "")
                        exec_time = data.get("execution_time", 0.0)
                        
                        # Metrics
                        m1, m2 = st.columns(2)
                        m1.metric("Execution Time", f"{exec_time:.2f}s")
                        m2.metric("Status", status.upper())
                        
                        # Status banner
                        if status in ["error", "timeout", "killed"] or stderr.strip():
                            st.error(f"Execution failed or produced errors (Status: {status})")
                        else:
                            st.success(f"Execution completed successfully (Status: {status})")
                            
                        # Terminal Outputs
                        st.markdown("### STDOUT")
                        if stdout:
                            st.code(stdout, language="bash")
                        else:
                            st.info("No standard output.")
                            
                        st.markdown("### STDERR")
                        if stderr:
                            st.code(stderr, language="bash")
                        else:
                            st.info("No standard error.")
                            
                    else:
                        st.error(f"Backend API Error: {response.status_code}")
                        st.code(response.text, language="bash")
                        
                except requests.exceptions.ConnectionError:
                    st.error("🚨 Connection Error: Cannot reach the Sandbox Backend.")
                    st.warning("Please ensure the FastAPI server is running: `uvicorn core.main:app --host 0.0.0.0 --port 8000`")
                except requests.exceptions.Timeout:
                    st.error("⏳ Timeout: The API took too long to respond.")
                except Exception as e:
                    st.error(f"Unexpected Error: {e}")
