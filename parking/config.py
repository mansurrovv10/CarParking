import os
from dotenv import load_dotenv


load_dotenv()
SECRET_KEY=os.getenv('SECRET_KEY')
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL не найден в .env")