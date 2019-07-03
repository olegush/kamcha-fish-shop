from dotenv import load_dotenv
import os
import logging
import redis
import requests
import json

from telegram.ext import Filters, Updater
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

DATABASE = None


def get_moltin_token(client_id_moltin):
    data = {
        'client_id': '{}'.format(client_id_moltin),
        'grant_type': 'implicit',
    }
    resp = requests.post('https://api.moltin.com/oauth/access_token', data=data)
    return json.loads(resp.text)['access_token']


def get_database_connection():
    global DATABASE
    if DATABASE is None:
        db_pwd = os.environ.get('REDIS_PWD')
        db_host = os.environ.get('REDIS_HOST')
        db_port = os.environ.get('REDIS_PORT')
        DATABASE = redis.Redis(host=db_host, port=db_port, password=db_pwd)
    return DATABASE


def error_callback(bot, update, error):
    try:
        logging.error(str(update))
        update.message.reply_text(text='Простите, возникла ошибка.')
    except Exception as err:
        logging.critical(err)


def get_products():
    headers = {
        'Authorization': 'Bearer {}'.format(token_moltin),
        'Content-Type': 'application/json',
    }
    resp = requests.get('https://api.moltin.com/v2/products', headers=headers)
    products = json.loads(resp.text)['data']
    return  {product['id']:product['name'] for product in products}


def get_product(id_product):
    headers = {
        'Authorization': 'Bearer {}'.format(token_moltin),
        'Content-Type': 'application/json',
    }
    resp = requests.get(f'https://api.moltin.com/v2/products/{id_product}', headers=headers)
    product = json.loads(resp.text)['data']
    id_img = product['relationships']['main_image']['data']['id']
    resp_img = requests.get(f'https://api.moltin.com/v2/files/{id_img}', headers=headers)
    href_img = json.loads(resp_img.text)['data']['link']['href']
    return product['name'], product['description'], product['meta']['display_price']['with_tax']['formatted'], product['meta']['stock']['level'], href_img


def start(bot, update):
    keyboard = list(
                InlineKeyboardButton(product_name, callback_data=product_id)
                for (product_id, product_name) in get_products().items())
    reply_markup = InlineKeyboardMarkup([keyboard])
    update.message.reply_text(text='Привет!', reply_markup=reply_markup)
    return 'HANDLE_MENU'


def handle_menu(bot, update):
    query = update.callback_query
    message_id = query.message.message_id
    chat_id = query.message.chat_id
    name, description, price, stock, href_img = get_product(query.data)
    text = f'{name}\n\n{description}\n\n{price} per kg\n\n{stock} on stock'
    bot.delete_message(chat_id=chat_id, message_id=message_id)
    keyboard = [[InlineKeyboardButton('Back', callback_data='goback')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_photo(chat_id=chat_id, photo=href_img, caption=text, reply_markup=reply_markup)
    return 'HANDLE_DESCRIPTION'


def handle_description(bot, update):
    query = update.callback_query
    message_id = query.message.message_id
    chat_id = query.message.chat_id
    bot.delete_message(chat_id=chat_id, message_id=message_id)
    if query.data == 'goback':
        return 'START'


def handle_users_reply(bot, update):
    DATABASE = get_database_connection()
    if update.message:
        user_reply = update.message.text
        chat_id = update.message.chat_id
    elif update.callback_query:
        user_reply = update.callback_query.data
        chat_id = update.callback_query.message.chat_id
    else:
        return
    if user_reply == '/start':
        user_state = 'START'
    else:
        user_state = DATABASE.get(chat_id).decode('utf-8')

    states_functions = {
        'START': start,
        'HANDLE_MENU': handle_menu,
        'HANDLE_DESCRIPTION': handle_description
        }
    state_handler = states_functions[user_state]
    next_state = state_handler(bot, update)
    DATABASE.set(chat_id, next_state)


if __name__ == '__main__':
    load_dotenv()
    token_telegram = os.getenv('TELEGRAM_TOKEN')
    token_moltin = get_moltin_token(os.getenv('MOLTIN_CLIENT_ID'))
    updater = Updater(token_telegram)
    dispatcher = updater.dispatcher
    dispatcher.add_handler(CallbackQueryHandler(handle_users_reply))
    dispatcher.add_handler(MessageHandler(Filters.text, handle_users_reply))
    dispatcher.add_handler(CommandHandler('start', handle_users_reply))
    dispatcher.add_error_handler(error_callback)
    updater.start_polling()
