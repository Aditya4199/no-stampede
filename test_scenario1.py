import asyncio
import httpx

async def main():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        # We need admin token and to create a show
        # Let's just use the server running locally...
        # Wait, I can't just run scenario 1 because I don't have the tokens
        pass

if __name__ == "__main__":
    asyncio.run(main())
