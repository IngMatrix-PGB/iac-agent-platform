"""`python -m iac_agent.api` starts the existing FastAPI server."""

from iac_agent.api.app import serve

if __name__ == "__main__":
    serve()
