"""`python -m app`: serve the API on 127.0.0.1 only."""

import uvicorn

from app.main import HOST, PORT, app

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
