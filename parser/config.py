import os
from dotenv import load_dotenv

load_dotenv()

# URL-адреси
BASE_URL = os.getenv('EPIC_BASE_URL', 'https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions')
WEBSITE_FIRST_PART = os.getenv('WEBSITE_FIRST_PART', 'https://www.epicgames.com/store/en-US/product/')
