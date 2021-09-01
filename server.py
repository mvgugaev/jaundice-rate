import aiohttp
from aiohttp import web
import asyncio
import logging
import adapters
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


async def fetch(session, url):
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.text()


@log_execution_time
async def process_article(
    session,
    morph,
    charged_words,
    url,
    group_result,
    timeout
):
    """Скачмвание и анализ объективности статьи."""
    try:
        async with async_timeout(timeout):
            html = await fetch(session, url)
            plaintext = adapters.SANITIZERS['inosmi_ru'](html, plaintext=True)
            words = await split_by_words(morph, plaintext)
            raiting = calculate_jaundice_rate(words, charged_words)
            group_result.append((
                url,
                ProcessingStatus.OK.value,
                raiting,
                len(words),
            ))
    except (aiohttp.InvalidURL, aiohttp.ClientResponseError):
        group_result.append((
            url,
            ProcessingStatus.FETCH_ERROR.value,
            None,
            None,
        ))
    except adapters.ArticleNotFound:
        group_result.append((
            url,
            ProcessingStatus.PARSING_ERROR.value,
            None,
            None,
        ))
    except asyncio.TimeoutError:
        group_result.append((
            url,
            ProcessingStatus.TIMEOUT.value,
            None,
            None,
        ))


async def process_articles_by_urls(urls, timeout=3):
    async with aiohttp.ClientSession() as session:
        morph = pymorphy2.MorphAnalyzer()
        charged_words = await get_icteric_words(ICTERIC_WORDS_FILE_PATHS)
        group_result = []
        async with create_task_group() as tg:
            for url in urls:
                tg.start_soon(
                    process_article,
                    session,
                    morph,
                    charged_words,
                    url,
                    group_result,
                    timeout,
                )

        return group_result


async def handle(request):
    urls_query_param = request.query.get('urls', None)
    urls = urls_query_param.split(',') if urls_query_param else []

    if len(urls) > 10:
        return web.json_response(
            {"error": "too many urls in request, should be 10 or less"},
            status=400,
        )
    group_data = await process_articles_by_urls(urls)
    return web.json_response(
        [
            {
                "status": redsult[1],
                "url": redsult[0],
                "score": redsult[2],
                "words_count": redsult[3],
            } for redsult in group_data
        ]
    )


def run_server():
    app = web.Application()
    app.add_routes([
        web.get('/', handle),
    ])
    web.run_app(app)


def test_process_article():
    assert asyncio.run(
        process_articles_by_urls(['1']),
    ) == [
        ('1', 'FETCH_ERROR', None, None),
    ]
    assert asyncio.run(
        process_articles_by_urls(['https://docs.python.org/ds']),
    ) == [
        ('https://docs.python.org/ds', 'FETCH_ERROR', None, None),
    ]
    assert asyncio.run(
        process_articles_by_urls(['https://yandex.ru']),
    ) == [
        ('https://yandex.ru', 'PARSING_ERROR', None, None),
    ]
    assert asyncio.run(
        process_articles_by_urls([TEST_ARTICLES[0]], timeout=0.1),
    ) == [
        (TEST_ARTICLES[0], 'TIMEOUT', None, None),
    ]
