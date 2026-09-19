import asyncio
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.parsers.hh_playwright import HHPlaywright

async def test():
    hh = HHPlaywright()
    st = await hh.check_negotiations_status()
    for s in st[:5]:
        print(s)

if __name__ == "__main__":
    asyncio.run(test())
