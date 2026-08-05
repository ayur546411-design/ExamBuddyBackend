import os
import asyncio
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')
print(f"Loaded API Key: {api_key[:5]}...{api_key[-5:]}")
genai.configure(api_key=api_key)

async def test():
    print("Testing models for generation...")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            try:
                model = genai.GenerativeModel(m.name)
                response = model.generate_content("Hello")
                print(f"SUCCESS: {m.name}")
                break
            except Exception as e:
                pass


asyncio.run(test())
