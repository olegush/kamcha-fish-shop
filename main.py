from dotenv import load_dotenv
import os
import logging
import redis
import requests

from telegram.ext import Filters, Updater
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


DATABASE = None
MOLTIN_API_URL = 'https://api.moltin.com/v2'
MOLTIN_API_OAUTH_URL = 'https://api.moltin.com/oauth/access_token'


def error_callback(bot, update, error):
    try:
        logging.error(str(update))
        update.message.reply_text(text='Error')
    except Exception as err:
        logging.critical(err)


def get_moltin_token(moltin_client_id, moltin_client_secret):
    data = {
        'client_id': '{}'.format(moltin_client_id),
        'client_secret': '{}'.format(moltin_client_secret),
        'grant_type': 'client_credentials',
    }
    resp = requests.post(MOLTIN_API_OAUTH_URL, data=data)
    return resp.json()['access_token']


def get_headers(token_moltin):
    return {
        'Authorization': 'Bearer {}'.format(token_moltin),
        'Content-Type': 'application/json',
    }


def get_database_connection():
    global DATABASE
    if DATABASE is None:
        db_pwd = os.environ.get('REDIS_PWD')
        db_host = os.environ.get('REDIS_HOST')
        db_port = os.environ.get('REDIS_PORT')
        DATABASE = redis.Redis(host=db_host, port=db_port, password=db_pwd)
    return DATABASE


def get_products():
    resp = requests.get(f'{MOLTIN_API_URL}/products', headers=headers)
    products = resp.json()['data']
    return  {product['id']:product['name'] for product in products}


def get_product(product_id):
    resp = requests.get(f'{MOLTIN_API_URL}/products/{product_id}', headers=headers)
    product = resp.json()['data']
    name = product['name']
    description = product['description']
    price = product['meta']['display_price']['with_tax']['formatted']
    stock = product['meta']['stock']['level']
    id_img = product['relationships']['main_image']['data']['id']
    resp_img = requests.get(f'{MOLTIN_API_URL}/files/{id_img}', headers=headers)
    href_img = resp_img.json()['data']['link']['href']
    return name, description, price, stock, href_img


def get_cart(cart_id):
    resp = requests.get(f'{MOLTIN_API_URL}/carts/{cart_id}/items', headers=headers)
    return resp.json()


def add_to_cart(cart_id, product_id, quantity):
    data = {
        'data': {
            'id': product_id,
            'type': 'cart_item',
            'quantity': quantity
        }
    }
    resp = requests.post(f'{MOLTIN_API_URL}/carts/{cart_id}/items', headers=headers, json=data)
    return resp.json()


def delete_from_cart(cart_id, item_id):
    resp = requests.delete(f'{MOLTIN_API_URL}/carts/{cart_id}/items/{item_id}', headers=headers)
    return resp.json()


def create_customer(chat_id, email):
    data = {
        'data': {
            'type': 'customer',
            'name': str(chat_id),
            'email': email
        }
    }
    resp = requests.post(f'{MOLTIN_API_URL}/customers', headers=headers, json=data)
    return resp.json()


def get_customer(customer_id):
    resp = requests.get(f'{MOLTIN_API_URL}/customers/{customer_id}', headers=headers)
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
    keyboard = [[InlineKeyboardButton(product_name, callback_data=product_id)]
                for (product_id, product_name) in get_products().items()]
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
    if query_data != '/start':
        bot.delete_message(chat_id=chat_id, message_id=message_id)
    display_menu(bot, chat_id)
    return 'HANDLE_MENU'


def handle_menu(bot, update):
    message_id, chat_id, query_data = get_query_data(update)
    if query_data == 'goto_cart':
        cart = get_cart(chat_id)
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        display_cart(bot, cart, chat_id)
        return 'HANDLE_CART'
    product_id = query_data
    name, description, price, stock, href_img = get_product(query_data)
    text = f'{name}\n\n{description}\n\n{price} per kg\n\n{stock} on stock'
    bot.delete_message(chat_id=chat_id, message_id=message_id)
    keyboard = [[InlineKeyboardButton('1 kg', callback_data=f'{product_id}:1'),
                InlineKeyboardButton('3 kg', callback_data=f'{product_id}:3'),
                InlineKeyboardButton('5 kg', callback_data=f'{product_id}:5')]]
    keyboard.append([InlineKeyboardButton('Main menu', callback_data='goto_menu')])
    keyboard.append([InlineKeyboardButton('Your cart', callback_data='goto_cart')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_photo(chat_id=chat_id, photo=href_img, caption=text, reply_markup=reply_markup)
    return 'HANDLE_DESCRIPTION'


def handle_description(bot, update):
    message_id, chat_id, query_data = get_query_data(update)
    if query_data == 'goto_menu':
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        display_menu(bot, chat_id)
        return 'HANDLE_MENU'
    elif query_data == 'goto_cart':
        cart = get_cart(chat_id)
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        display_cart(bot, cart, chat_id)
        return 'HANDLE_CART'
    else:
        product_id, quantity = query_data.split(':')
        cart = add_to_cart(chat_id, product_id, int(quantity))
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        display_cart(bot, cart, chat_id)
        return 'HANDLE_CART'


def handle_cart(bot, update):
    message_id, chat_id, query_data = get_query_data(update)
    if query_data == 'goto_menu':
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        display_menu(bot, chat_id)
        return 'HANDLE_MENU'
    elif query_data == 'goto_contacts':
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        display_waiting_contacts(bot, chat_id)
        return 'HANDLE_CONTACTS'
    else:
        delete_from_cart(chat_id, query_data)
        cart = get_cart(chat_id)
        bot.delete_message(chat_id=chat_id, message_id=message_id)
        display_cart(bot, cart, chat_id)
        return 'HANDLE_CART'


def handle_contacts(bot, update):
    message_id, chat_id, query_data = get_query_data(update)
    bot.delete_message(chat_id=chat_id, message_id=message_id)
    customer_data = create_customer(chat_id, query_data)
    customer_id = customer_data['data']['id']
    customer_data = get_customer(customer_id)
    customer_email = customer_data['data']['email']
    bot.send_message(text=f"Your email: {customer_email}. Please await the"
                            " order's confirm. Thank you!", chat_id=chat_id)


def handle_users_reply(bot, update):
    # Main function. Handles all user's actions. Gets current statement,
    # runs relevant function and set new statement.
    DATABASE = get_database_connection()
    message_id, chat_id, query_data = get_query_data(update)
    if query_data == '/start':
        user_state = 'START'
    else:
        user_state = DATABASE.get(chat_id).decode('utf-8')
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
    except Exception as err:
        print(err)
    DATABASE.set(chat_id, next_state)


if __name__ == '__main__':
    load_dotenv()
    telegram_telegram = os.getenv('TELEGRAM_TOKEN')
    moltin_client_id = os.getenv('MOLTIN_CLIENT_ID')
    moltin_client_secret = os.getenv('MOLTIN_CLIENT_SECRET')
    token_moltin = get_moltin_token(moltin_client_id, moltin_client_secret)
    headers = get_headers(token_moltin)
    updater = Updater(telegram_telegram)
    dispatcher = updater.dispatcher
    dispatcher.add_handler(CallbackQueryHandler(handle_users_reply))
    dispatcher.add_handler(MessageHandler(Filters.text, handle_users_reply))
    dispatcher.add_handler(CommandHandler('start', handle_users_reply))
    dispatcher.add_error_handler(error_callback)
    updater.start_polling(clean=True)
