import os
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
r = client.models.generate_content(
    model="gemma-4-26b-a4b-it",
    contents="Say hi in 5 words",
)
print(r.text)