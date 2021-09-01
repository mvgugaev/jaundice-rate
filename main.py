import aiohttp
import asyncio
import adapters
import logging
import pymorphy2
import aiofiles
import decorator
import time
from async_timeout import timeout as async_timeout
from enum import Enum
from anyio import create_task_group
from pathlib import Path
from text_tools import split_by_words, calculate_jaundice_rate

ICTERIC_WORDS_FILE_PATHS = (
    'charged_dict/negative_words.txt',
    'charged_dict/positive_words.txt',
)

TEST_ARTICLES = (
    'https://inosmi.ru/military/20210901/250424381.html',
    'https://inosmi.ru/politic/20210901/250427261.html',
    'https://inosmi.ru/social/20210901/250422682.html',
    'https://inosmi.ru/military/20210901/250424dsfsdf381.html',
    'https://lenta.ru/brief/2021/08/26/afg_terror/',
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('root')


@decorator.decorator
async def log_execution_time(task, *args, **kwargs):
    start_time = time.monotonic()
    res = await task(*args, **kwargs)
    result_time = time.monotonic() - start_time
    logger.info(f'Анализ закончен за {result_time:.2f} сек')
    return res


class ProcessingStatus(Enum):
    OK = 'OK'
    FETCH_ERROR = 'FETCH_ERROR'
    PARSING_ERROR = 'PARSING_ERROR'
    TIMEOUT = 'TIMEOUT'


async def get_icteric_words(file_paths):
    words = []

    for path in file_paths:
        async with aiofiles.open(Path(path), mode='r') as file:
            words += (await file.read()).splitlines()
    
    return words


async def fetch(session, url, timeout):
    async with session.get(url) as response:
        response.raise_for_status()
        async with async_timeout(timeout):
            return await response.text()

@log_execution_time
async def process_article(session, morph, charged_words, url, group_result):
    try:
        html = await fetch(session, url, 0.5)
        plaintext = adapters.SANITIZERS['inosmi_ru'](html, plaintext=True)
        words = split_by_words(morph, plaintext)
        raiting = calculate_jaundice_rate(words, charged_words)
        group_result.append((
            url,
            ProcessingStatus.OK,
            raiting, 
            len(words),
        ))
    except (aiohttp.InvalidURL, aiohttp.ClientResponseError):
        group_result.append((
            url,
            ProcessingStatus.FETCH_ERROR,
            None,
            None,
        ))
    except adapters.ArticleNotFound:
        group_result.append((
            url,
            ProcessingStatus.PARSING_ERROR,
            None,
            None,
        ))
    except asyncio.TimeoutError:
        group_result.append((
            url,
            ProcessingStatus.TIMEOUT,
            None,
            None,
        ))


async def main():
    async with aiohttp.ClientSession() as session:
        morph = pymorphy2.MorphAnalyzer()
        charged_words = await get_icteric_words(ICTERIC_WORDS_FILE_PATHS)
        group_result = []
        async with create_task_group() as tg:
            for url in TEST_ARTICLES:
                tg.start_soon(
                    process_article,
                    session,
                    morph,
                    charged_words,
                    url,
                    group_result,
                )
        
        for result in group_result:
            print(f'URL: {result[0]}')
            print(f'Статус: {result[1].value}')
            print(f'Рейтинг: {result[2]}')
            print(f'Слов в статье: {result[3]}')


asyncio.run(main())
