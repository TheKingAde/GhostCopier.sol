import sys
from app import create_app
from app.config import Config

app = create_app()

if __name__ == "__main__":
    try:
        app.run(host=Config.HOST, port=Config.PORT)
    except (KeyboardInterrupt, EOFError):
        print("\nShutting down...")
        sys.exit(0)