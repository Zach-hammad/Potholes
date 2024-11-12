from flask import *

app = Flask(__name__)

@app.route('/', methods=['GET','POST'])
def index():
    if request.method=='POST':
        data = request.form['fileUploadImages']

        return f"Data received: {data}"
    return render_template('index.html')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)