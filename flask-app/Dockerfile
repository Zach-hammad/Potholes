FROM python:3.12

WORKDIR /app

COPY . .

RUN pip install -r requirements.txt

EXPOSE 8501

# HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

# ENTRYPOINT ["streamlit", "run", "/app/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
CMD ["python", "app.py"]

# CMD ["flask", "--app", "api", "run" "--host=0.0.0.0", "-p", "8501"]

# ENTRYPOINT ["python", "api.py"]
