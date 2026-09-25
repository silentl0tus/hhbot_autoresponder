import asyncio

async def main():
    letter = None
    if not letter:
        letter_box = {"text": "hello"}
        async def gen():
            letter_box["text"] = "world"
            return "world"
        letter = gen
        
    await letter()
    
    print("letter_box in locals():", "letter_box" in locals())
    print("final_letter:", letter_box["text"] if callable(letter) and "letter_box" in locals() else (letter if not callable(letter) else ""))

asyncio.run(main())
