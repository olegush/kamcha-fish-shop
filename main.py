from dotenv import load_dotenv
import os
import logging
import redis
import requests

from telegram.ext import Filters, Updater
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


MOLTIN_API_URL = 'https://api.moltin.com/v2'
MOLTIN_API_OAUTH_URL = 'https://api.moltin.com/oauth/access_token'
MOLTIN_ERR_MSG = 'Moltin API returns error:'
TELEGRAM_ERR_MSG = 'Telegram API returns error:'

class MoltinError(Exception):
    def __init__(self, message):
        self.message = message


database = None


def error_callback(bot, update, error):
    try:
        logging.error(str(update))
        update.message.reply_text(text='Error')
    except Exception as e:
        logging.critical(f'{TELEGRAM_ERR_MSG} {e}')


def get_headers(moltin_client_id, moltin_client_secret):
    data = {'client_id': str(moltin_client_id),
            'client_secret': str(moltin_client_secret),
            'grant_type': 'client_credentials'}
    try:
        resp = requests.post(MOLTIN_API_OAUTH_URL, data=data)
        if 'errors' in resp.json():
            raise MoltinError(f'{MOLTIN_ERR_MSG} {resp.json()}')
        moltin_token = resp.json()['access_token']
        return {
            'Authorization': 'Bearer {}'.format(moltin_token),
            'Content-Type': 'application/json'
        }
    except requests.exceptions.ConnectionError as e:
        raise MoltinError(f'{MOLTIN_ERR_MSG} {e}')


def get_database_connection():
    global database
    if database is None:
        db_pwd = os.environ.get('REDIS_PWD')
        db_host = os.environ.get('REDIS_HOST')
        db_port = os.environ.get('REDIS_PORT')
        database = redis.Redis(host=db_host, port=db_port, password=db_pwd)
    return database


def get_products():
    global headers
    resp = requests.get(f'{MOLTIN_API_URL}/products', headers=headers)
    if 'errors' in resp.json():
        raise MoltinError(f'{MOLTIN_ERR_MSG} {resp.json()}')
    products = resp.json()['data']
    return  {product['id']:product['name'] for product in products}


def get_product(product_id):
    global headers
    resp = requests.get(f'{MOLTIN_API_URL}/products/{product_id}', headers=headers)
    if 'errors' in resp.json():
        raise MoltinError(f'{MOLTIN_ERR_MSG} {resp.json()}')
    product = resp.json()['data']
    name = product['name']
    description = product['description']
    price = product['meta']['display_price']['with_tax']['formatted']
    stock = product['meta']['stock']['level']
    id_img = product['relationships']['main_image']['data']['id']
    resp_img = requests.get(f'{MOLTIN_API_URL}/files/{id_img}', headers=headers)
    if 'errors' in resp.json():
        raise MoltinError(f'{MOLTIN_ERR_MSG} {resp.json()}')
    href_img = resp_img.json()['data']['link']['href']
    return name, description, price, stock, href_img


def get_cart(cart_id):
    global headers
    resp = requests.get(f'{MOLTIN_API_URL}/carts/{cart_id}/items', headers=headers)
    if 'errors' in resp.json():
        raise MoltinError(f'{MOLTIN_ERR_MSG} {resp.json()}')
    return resp.json()


def add_to_cart(cart_id, product_id, quantity):
    global headers
    data = {
        'data': {
            'id': product_id,
            'type': 'cart_item',
            'quantity': quantity
        }
    }
    resp = requests.post(f'{MOLTIN_API_URL}/carts/{cart_id}/items', headers=headers, json=data)
    if 'errors' in resp.json():
        raise MoltinError(f'{MOLTIN_ERR_MSG} {resp.json()}')
    return resp.json()


def delete_from_cart(cart_id, item_id):
    global headers
    resp = requests.delete(f'{MOLTIN_API_URL}/carts/{cart_id}/items/{item_id}', headers=headers)
    if 'errors' in resp.json():
        raise MoltinError(f'{MOLTIN_ERR_MSG} {resp.json()}')
    return resp.json()


def create_customer(chat_id, email):
    global headers
    data = {
        'data': {
            'type': 'customer',
            'name': str(chat_id),
            'email': email
        }
    }
    resp = requests.post(f'{MOLTIN_API_URL}/customers', headers=headers, json=data)
    if 'errors' in resp.json():
        raise MoltinError(f'{MOLTIN_ERR_MSG} {resp.json()}')
    return resp.json()


def get_customer(customer_id):
    global headers
    resp = requests.get(f'{MOLTIN_API_URL}/customers/{customer_id}', headers=headers)
    if 'errors' in resp.json():
        raise MoltinError(f'{MOLTIN_ERR_MSG} {resp.json()}')
    return resp.json()


def get_query_data(update):
    if update.message:
        query = update.message
        return query.message_id, query.chat_id, query.text
    elif update.callback_query:
        query = update.callback_query
        return query.message.message_id, query.message.chat_id, query.data
    else:
        return


def display_menu(bot, chat_id):
    products = get_products().items()
    keyboard = [[InlineKeyboardButton(product_name, callback_data=product_id)]
                for (product_id, product_name) in products]
    keyboard.append([InlineKeyboardButton('Your cart', callback_data='goto_cart')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(text='MAIN MENU', chat_id=chat_id, reply_markup=reply_markup)


def display_cart(bot, cart, chat_id):
    products = '\n'.join((f"{product['name']}: {product['quantity']} kg for {product['meta']['display_price']['with_tax']['value']['formatted']}"
                            for product in cart['data']))
    total = cart['meta']['display_price']['with_tax']['formatted']
    keyboard = [[InlineKeyboardButton(f"Delete {product['name']}", callback_data=product['id'])]
                for product in cart['data']]
    keyboard.append([InlineKeyboardButton('Main menu', callback_data='goto_menu')])
    keyboard.append([InlineKeyboardButton('Order now', callback_data='goto_contacts')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(text=f"YOUR CART:\n{products}\nTotal:{total}", chat_id=chat_id, reply_markup=reply_markup)


def display_waiting_contacts(bot, chat_id):
    bot.send_message(text=f"YOUR CONTACTS:\nTo proceed the order please "
                            "send us your email.", chat_id=chat_id)


def start(bot, update):
    message_id, chat_id, query_data = get_query_data(update)
    display_menu(bot, chat_id)
    if query_data != '/start':
        bot.delete_message(chat_id=chat_id, message_id=message_id)
    return 'HANDLE_MENU'


def handle_menu(bot, update):
    message_id, chat_id, query_data = get_query_data(update)
    if query_data == 'goto_cart':
        cart = get_cart(chat_id)
        display_cart(bot, cart, chat_id)
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        return 'HANDLE_CART'
    product_id = query_data
    name, description, price, stock, href_img = get_product(query_data)
    text = f'{name}\n\n{description}\n\n{price} per kg\n\n{stock} on stock'
    keyboard = [[InlineKeyboardButton('1 kg', callback_data=f'{product_id}:1'),
                InlineKeyboardButton('3 kg', callback_data=f'{product_id}:3'),
                InlineKeyboardButton('5 kg', callback_data=f'{product_id}:5')]]
    keyboard.append([InlineKeyboardButton('Main menu', callback_data='goto_menu')])
    keyboard.append([InlineKeyboardButton('Your cart', callback_data='goto_cart')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_photo(chat_id=chat_id, photo=href_img, caption=text, reply_markup=reply_markup)
    bot.delete_message(chat_id=chat_id, message_id=message_id)
    return 'HANDLE_DESCRIPTION'


def handle_description(bot, update):
    message_id, chat_id, query_data = get_query_data(update)
    if query_data == 'goto_menu':
        display_menu(bot, chat_id)
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        return 'HANDLE_MENU'
    elif query_data == 'goto_cart':
        cart = get_cart(chat_id)
        display_cart(bot, cart, chat_id)
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        return 'HANDLE_CART'
    else:
        product_id, quantity = query_data.split(':')
        cart = add_to_cart(chat_id, product_id, int(quantity))
        display_cart(bot, cart, chat_id)
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        return 'HANDLE_CART'


def handle_cart(bot, update):
    message_id, chat_id, query_data = get_query_data(update)
    if query_data == 'goto_menu':
        display_menu(bot, chat_id)
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        return 'HANDLE_MENU'
    elif query_data == 'goto_contacts':
        display_waiting_contacts(bot, chat_id)
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        return 'HANDLE_CONTACTS'
    else:
        delete_from_cart(chat_id, query_data)
        cart = get_cart(chat_id)
        display_cart(bot, cart, chat_id)
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        return 'HANDLE_CART'


def handle_contacts(bot, update):
    message_id, chat_id, query_data = get_query_data(update)
    customer_data = create_customer(chat_id, query_data)
    customer_id = customer_data['data']['id']
    customer_data = get_customer(customer_id)
    customer_email = customer_data['data']['email']
    bot.send_message(text=f"Your email: {customer_email}. Please await the"
                            " order's confirm. Thank you!", chat_id=chat_id)
    bot.delete_message(chat_id=chat_id, message_id=message_id)


def handle_users_reply(bot, update):
    # Handles all user's actions. Gets current statement,
    # runs relevant function and set new statement.
    database = get_database_connection()
    message_id, chat_id, query_data = get_query_data(update)
    if query_data == '/start':
        user_state = 'START'
    else:
        user_state = database.get(chat_id).decode('utf-8')
    states_functions = {
        'START': start,
        'HANDLE_MENU': handle_menu,
        'HANDLE_DESCRIPTION': handle_description,
        'HANDLE_CART': handle_cart,
        'HANDLE_CONTACTS': handle_contacts
        }
    state_handler = states_functions[user_state]
    try:
        next_state = state_handler(bot, update)
        database.set(chat_id, next_state)
    except MoltinError as e:
        raise e
    except Exception as e:
        raise e



def main(telegram_token, moltin_client_id, moltin_client_secret):
    # Get headers for requests to Moltin, creates the Updater,
    # registers all handlers and starts polling updates from Telegram.
    global headers
    try:
        headers = get_headers(moltin_client_id, moltin_client_secret)
        updater = Updater(telegram_token)
        dispatcher = updater.dispatcher
        dispatcher.add_handler(CallbackQueryHandler(handle_users_reply))
        dispatcher.add_handler(MessageHandler(Filters.text, handle_users_reply))
        dispatcher.add_handler(CommandHandler('start', handle_users_reply))
        dispatcher.add_error_handler(error_callback)
        updater.start_polling(clean=True)
    except MoltinError as e:
        logging.critical(e)
    except Exception as e:
        logging.critical(e)


if __name__ == '__main__':
    load_dotenv()
    telegram_token = os.environ.get('TELEGRAM_TOKEN')
    moltin_client_id = os.environ.get('MOLTIN_CLIENT_ID')
    moltin_client_secret = os.environ.get('MOLTIN_CLIENT_SECRET')
    main(telegram_token, moltin_client_id, moltin_client_secret)
