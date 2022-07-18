"""
filename: main.py
author: hexsix <hexsixology@gmail.com>
date: 2022/07/18
description: 
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, List

from bs4 import BeautifulSoup
import feedparser
import httpx
import redis


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger()

CHAT_ID = os.environ['CHAT_ID']
TG_TOKEN = os.environ['TG_TOKEN']
REDIS = redis.from_url(os.environ['REDIS_URL'])
CONFIGS = json.loads(os.environ['CONFIGS'])


def rss_url_generator() -> Any:
    for key in CONFIGS:
        artist_name, artist_id = key, CONFIGS[key]
        rss_url = f'https://rsshub.app/ncm/artist/{artist_id}'
        yield artist_name, rss_url


def download(rss_url: str) -> Dict:
    logger.info('Downloading RSS ...')
    rss_json = None
    for retry in range(3):
        logger.info(f'The {retry + 1}th attempt, 3 attempts in total.')
        try:
            with httpx.Client() as client:
                response = client.get(rss_url, timeout=10.0)
            rss_json = feedparser.parse(response.text)
            if rss_json:
                break
        except Exception as e:
            logger.info(f'Failed, next attempt will start soon: {e}')
            time.sleep(6)
    if not rss_json:
        raise Exception('Failed to download RSS.')
    logger.info('Succeed to download RSS.\n')
    return rss_json


def parse(rss_json: Dict) -> List[Dict[str, Any]]:
    logger.info('Parsing RSS ...')
    items = []
    filtered_cnt = 0
    for entry in rss_json['entries']:
        try:
            item = dict()
            item['title'] = entry['title']
            item['author'] = entry['author']
            item['published'] = entry['published']
            item['link'] = entry['link']
            logger.info(f'{item["link"]}')
            item['album_id'] = re.search(r'\d{4,15}', entry['link']).group()
            item['cover'] = re.search(r'https:\/\/p1.music.126.net\/[^\"\s]*', entry['summary']).group()
            items.append(item)
        except Exception as e:
            logger.info(f'Exception: {e}')
            continue
    logger.info(
        f"Parse RSS End. {len(items)}/{len(rss_json['entries'])} Succeed.")
    return items


def send(chat_id: str, photo: str, caption: str, item: Dict) -> bool:
    logger.info(f'Send album: {item["title"]}, id: {item["album_id"]} ...')
    if photo:
        target = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
        params = {
            'chat_id': chat_id,
            'photo': photo,
            'caption': caption
        }
        try:
            with httpx.Client() as client:
                response = client.post(target, params=params)
            if response.json()['ok']:
                logger.info(f'Succeed to send album: {item["title"]}, id: {item["album_id"]}.')
                return True
            else:
                logger.warn(f'Telegram api returns {response.json()}')
                logger.warn(f'sendPhoto Failed, photo: {photo}, caption: {caption}')
        except Exception as e:
            logger.error(f'Exception: {e}')
            pass
        logger.error(f'Failed to send album: {item["title"]}, id: {item["album_id"]}.\n')
        return False
    else:
        target = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        params = {
            'chat_id': chat_id,
            'parse_mode': 'MarkdownV2',
            'text': caption
        }
        try:
            with httpx.Client() as client:
                response = client.post(target, params=params)
            if response.json()['ok']:
                logger.info(f'Succeed to send album: {item["title"]}, id: {item["album_id"]}.')
                return True
            else:
                logger.warn(f'Telegram api returns {response.json()}')
                logger.warn(f'sendMessage Failed, caption: {caption}')
        except Exception as e:
            logger.error(f'Exception: {e}')
            pass
        logger.error(f'Failed to send album: {item["title"]}, id: {item["album_id"]}.\n')
        return False


def escape(text: str) -> str:
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for escape_char in escape_chars:
        text = text.replace(escape_char, '\\' + escape_char)
    return text


def construct_params(item: Dict):
    album_id = item['album_id']
    photo = item['cover']
    caption = f'\\#{album_id}\n' \
              f'*{escape(item["title"])}*\n' \
              f'\n' \
              f'{escape(item["author"])}\n' \
              f'\n' \
              f'{escape(item["link"])}'
    return photo, caption, album_id


def filter(item: Dict) -> bool:
    if REDIS.exists(item['album_id']):
        return True
    return False


def redis_set(album_id: str) -> bool:
    for retry in range(5):
        logger.info(f'The {retry + 1}th attempt to set redis, 5 attempts in total.')
        try:
            if REDIS.set(rj_code, 'sent', ex=64281600):  # expire after 2 year
                logger.info(f'Succeed to set redis {album_id}.\n')
                return True
        except Exception:
            logger.info('Failed to set redis, '
                        'the next attempt will start in 6 seconds.')
            time.sleep(6)
    logger.info(f'Failed to set redis, {album_id} may be sent twice.\n')
    return False


def main() -> None:
    logger.info('============ App Start ============')
    for artist_name, rss_url in rss_url_generator():
        logger.info(f'{artist_name}：{rss_url}')
        # download rss
        rss_json = download(rss_url)
        # parse rss
        items = parse(rss_json)
        # filter by redis already sent
        filtered_items = [item for item in items if not filter(item)]
        logger.info(f'{len(filtered_items)}/{len(items)} filtered by already sent.\n')
        # send messages
        for item in filtered_items:
            photo, caption, album_id = construct_params(item)
            if send(CONFIGS[rss_author], photo, caption, item):
                redis_set(album_id)
                time.sleep(10)
    logger.info('============ App End ============')


if __name__ == '__main__':
    main()
