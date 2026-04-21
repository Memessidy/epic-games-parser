import aiohttp
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from app_logging.logger import logger
from parser import config


@dataclass
class Game:
    name: str
    description: str
    url: str
    image: Optional[str]
    start_date: Optional[str]  # ISO рядок від Epic
    end_date: Optional[str]  # ISO рядок від Epic
    price: str

    def _format_date(self, date_str: Optional[str]) -> str:
        """Перетворює ISO дату від Epic у формат dd.mm.YYYY HH:mm"""
        if not date_str:
            return "—"

        try:
            # Epic надсилає дату у форматі: 2026-04-21T15:30:00.000Z
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            return date_str[:16] if date_str else "—"

    @property
    def start_date_formatted(self) -> str:
        return self._format_date(self.start_date)

    @property
    def end_date_formatted(self) -> str:
        return self._format_date(self.end_date)


class EpicFreeGamesParser:
    def __init__(self):
        self.current_games: List[Game] = []
        self.future_games: List[Game] = []

    def clear(self) -> None:
        self.current_games.clear()
        self.future_games.clear()

    @staticmethod
    def _build_url(item: Dict[str, Any]) -> Optional[str]:
        """Надійне формування посилання на гру."""
        product_slug = item.get("productSlug")
        if product_slug:
            # Іноді slug має вигляд "game/xxx" - беремо першу частину
            slug = product_slug.split("/")[0]
            return f"{config.WEBSITE_FIRST_PART}{slug}"

        # Резервний варіант через offerMappings
        offer_mappings = item.get("offerMappings") or []
        if offer_mappings:
            page_slug = offer_mappings[0].get("pageSlug")
            if page_slug:
                return f"{config.WEBSITE_FIRST_PART}{page_slug}"

        logger.warning("Не вдалося сформувати URL для гри: %s", item.get("title"))
        return None

    @staticmethod
    def _extract_image(item: Dict[str, Any]) -> Optional[str]:
        """Шукаємо широке зображення (OfferImageWide)."""
        for img in item.get("keyImages", []):
            if img.get("type") == "OfferImageWide":
                return img.get("url")
        return None

    def _parse_promotion(self, promotions: List[Dict], item: Dict[str, Any]) -> Optional[Game]:
        """Єдина функція для парсингу поточних і майбутніх промо."""
        if not promotions:
            return None

        # Беремо першу групу промо (зазвичай так влаштовано в Epic)
        promo_group = promotions[0]
        promo_offers = promo_group.get("promotionalOffers") or []

        for offer in promo_offers:
            discount_setting = offer.get("discountSetting") or {}
            if discount_setting.get("discountPercentage") != 0:
                continue  # пропускаємо, якщо не безкоштовна

            name = item.get("title")
            description = item.get("description")
            start_date = offer.get("startDate")
            end_date = offer.get("endDate")

            price_info = item.get("price", {}).get("totalPrice", {}).get("fmtPrice", {})
            price = price_info.get("originalPrice", "Free")

            image = self._extract_image(item)
            url = self._build_url(item)

            if not name or not url:
                logger.warning("Пропущено гру без назви або URL: %s", name)
                return None

            return Game(
                name=name,
                description=description or "",
                url=url,
                image=image,
                start_date=start_date,
                end_date=end_date,
                price=price,
            )

        return None

    def _process_games(self, elements: List[Dict[str, Any]]) -> None:
        """Обробка всіх елементів із відповіді."""
        for item in elements:
            promotions = item.get("promotions") or {}
            current = promotions.get("promotionalOffers") or []
            upcoming = promotions.get("upcomingPromotionalOffers") or []

            if current:
                game = self._parse_promotion(current, item)
                if game:
                    self.current_games.append(game)
            elif upcoming:  # лише якщо немає поточних
                game = self._parse_promotion(upcoming, item)
                if game:
                    self.future_games.append(game)

    async def _fetch_data(self) -> List[Dict[str, Any]]:
        """Асинхронний запит із таймаутом та обробкою помилок."""
        timeout = aiohttp.ClientTimeout(total=15)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/134.0 Safari/537.36"
        }

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            try:
                async with session.get(config.BASE_URL) as resp:
                    if resp.status != 200:
                        logger.error("HTTP статус %s під час запиту %s", resp.status, config.BASE_URL)
                        return []

                    data = await resp.json()
                    return data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])

            except asyncio.TimeoutError:
                logger.error("Таймаут під час запиту до Epic Games")
            except aiohttp.ClientError as e:
                logger.error("Помилка мережі: %s", e)
            except Exception as e:  # останній захист
                logger.exception("Неочікувана помилка під час отримання даних: %s", e)

            return []

    async def parse(self) -> None:
        """Основний метод парсингу."""
        self.clear()
        elements = await self._fetch_data()

        if not elements:
            logger.warning("Не отримано даних від Epic Games")
            return

        self._process_games(elements)
        logger.info("Знайдено поточних безкоштовних ігор: %d | Майбутніх: %d",
                    len(self.current_games), len(self.future_games))

    @property
    def free_games(self) -> Tuple[List[Game], List[Game]]:
        return self.current_games, self.future_games


# ====================== Запуск ======================
def print_games(games):
    for game in games:
        print(f"🎮 {game.name}")
        print(f"   Ціна: {game.price}")
        print(f"   З {game.start_date_formatted}  →  До {game.end_date_formatted}")
        print(f"   Посилання: {game.url}")
        print(f"   Опис: {game.description[:40]}...\n")
        if game.image:
            print(f"   Зображення: {game.image}")
        print("-" * 80)


async def main():
    parser = EpicFreeGamesParser()
    await parser.parse()

    current, future = parser.free_games

    print("=== Поточні безкоштовні ігри ===")
    print_games(current)
    print(f"\nУсього поточних безкоштовних ігор: {len(current)}\n")

    print("=== Майбутні безкоштовні ігри ===")
    print_games(future)
    print(f"Усього майбутніх ігор: {len(future)}")


if __name__ == "__main__":
    asyncio.run(main())
