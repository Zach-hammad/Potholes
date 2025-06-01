from flask import Blueprint, render_template

# Create a Blueprint object to group together related routes (views)
# 'dashboard' is the blueprints's name. and __name__ tells Flask where the code lives 
bp = Blueprint('dashboard', __name__)

@bp.route('/') # Register this function to handle GET requests to the root path '/'
def index():
    """
    Render the main index page.
    Visiting '/' in your browser will return the 'index.html' template.
    """
    return render_template('index.html') # Look into your templates folder for index.html template

@bp.route('/dashboard') # Register this function to handel GET requests to  /dashbaord
def dashboard():
    return render_template('dashboard.html') # Look into your templates/ folder for dashboard.html