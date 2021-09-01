import aiohttp
import asyncio
import adapters
import pymorphy2
from text_tools import split_by_words, calculate_jaundice_rate


ICTERIC_WORDS = (
    'опасность',
    'мощный',
    'серьёзный',
)

async def fetch(session, url):
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.text()


async def main():
    async with aiohttp.ClientSession() as session:
        html = await fetch(session, 'https://inosmi.ru/military/20210901/250424381.html')
        plaintext = adapters.SANITIZERS['inosmi_ru'](html, plaintext=True)
        morph = pymorphy2.MorphAnalyzer()
        words = split_by_words(morph, plaintext)
        raiting = calculate_jaundice_rate(words, ICTERIC_WORDS)
        print(f'Рейтинг: {raiting}')
        print(f'Слов в статье: {len(words)}')


asyncio.run(main())
