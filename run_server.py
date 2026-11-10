import os

import uvicorn

if __name__ == "__main__":
    host = "0.0.0.0" if os.getenv("PORT") else "127.0.0.1"
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("backend.main:app", host=host, port=port, reload=False)
