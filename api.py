from flask import Flask
import streamlit as st

def display_landing_page():
    st.title("Welcome!")
    st.button("Button!")

app = Flask(__name__)

@app.route("/v1/")
def hello_world():
    return "<p>Hello, World!</p>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8501, debug=True)
    display_landing_page()