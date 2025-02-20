from flask import Flask
from config import Config
from extensions import db, login_manager

def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)
    
    # Initialise extensions
    db.init_app(app)
    login_manager.init_app(app)
    
    with app.app_context():
        # Import models so that they are registered with SQLAlchemy
        import models  
        db.create_all()
    
    # Register your blueprint (from routes.py)
    from routes import bp as main_bp
    app.register_blueprint(main_bp)
    
    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7070)
