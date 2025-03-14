import os
import asyncio
import re
from datetime import datetime, timedelta, timezone
import random

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv
from liqpay.liqpay3 import LiqPay
import pymongo


load_dotenv()
TOKEN = os.getenv("TOKEN")
bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(bot=bot)

PUBLIC_KEY = os.getenv("PUBLIC_KEY")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
liq = LiqPay(PUBLIC_KEY, PRIVATE_KEY)

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client.test_task
coll_users = db.users
coll_products = db.products
coll_payments = db.payments



coll_products.delete_many({'id':{"$exists":True}})
coll_products.insert_many([
    {'id': 1, 'emj': '🧄', 'name': 'Часник', 'price':20, 'pic_name': 'garlic.png', 'desc': 'Ароматна пряність із гострим смаком, що додає стравам пікантності та має корисні властивості.'},
    {'id': 2, 'emj': '🍎', 'name': 'Яблуко', 'price':30.99, 'pic_name': 'apple.png', 'desc': 'Соковитий фрукт із хрусткою текстурою та солодко-кислим смаком, джерело вітамінів і свіжості.'},
    {'id': 3, 'emj': '🍠', 'name': 'Батат', 'price': 80, 'pic_name': 'batat.png', 'desc': 'Солодкувата картопля з ніжною текстурою, багата на корисні речовини та чудова для запікання.'}
])



@dp.message(F.chat.type == "private", Command("start"))
async def say_hello(message: Message) -> None:
    if not coll_users.find_one({"id": message.from_user.id}):
        coll_users.insert_one({"id": message.from_user.id, "cart":{}})

    builder = ReplyKeyboardBuilder()
    builder.button(text="🧺 Продукти")
    builder.button(text="🛒 Корзина")
    keyboard = builder.as_markup(resize_keyboard=True)
    answer = (f"👋 Привіт, <b>{message.from_user.full_name}</b>!\n\n"
              f"Список продуктів можеш переглянути за командою /products або ж за допомогою кнопки нижче:")

    await message.answer(answer, reply_markup=keyboard)


@dp.message(F.chat.type == "private", Command("products"))
@dp.message(F.chat.type == "private", F.text == "🧺 Продукти")
async def get_products(message: Message) -> None:
    products = tuple(coll_products.find())
    for product in products:
        text = (f"{product['emj']} <b>{product['name']}</b>\n\n"
                f"<i>{product['desc']}</i>\n\n"
                f"Ціна: {product['price']} грн/кг")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🛒 Додати в корзину", callback_data=f"cart_add_{product['id']}")
        ]])
        photo = FSInputFile(f"product_pics/{product['pic_name']}")
        await message.answer_photo(caption=text, reply_markup=keyboard, photo=photo)

@dp.callback_query(F.data.startswith("cart_add_"))
async def cart_add_callback(call: CallbackQuery) -> None:
    product_id = re.findall(r"\d+", call.data)[0]
    user_id = call.from_user.id
    user = coll_users.find_one({"id": user_id})
    cart = user["cart"]

    if product_id in list(cart.keys()):
        cart[product_id] = cart[product_id] + 1
        coll_users.update_one({"id":user_id}, {"$set":{"cart": cart}})
        await call.answer("✅ Ще один екземпляр було додано до вашої корзини!", show_alert=True)
    else:
        cart[product_id] = 1
        coll_users.update_one({"id":user_id}, {"$set":{"cart": cart}})
        await call.answer("✅ Продукт додано до вашої корзини!", show_alert=True)

@dp.message(F.chat.type == "private", F.text == "🛒 Корзина")
async def get_products(message: Message) -> None:
    text = "🛒 <b>Корзина</b>\n\n"

    user = coll_users.find_one({'id':message.from_user.id})
    products_count = user['cart']
    if products_count:
        total = 0
        for prod_id in list(products_count.keys()):
            product = coll_products.find_one({'id':int(prod_id)})
            total += products_count[prod_id] * product['price']
            text += f"• {product['emj']} {product['name']} – {products_count[prod_id]} кг\n"
        text += f"\nЗагальна сума: {total} грн"

        buttons = [
            [InlineKeyboardButton(text="💰 Оплатити замовлення", callback_data="buy")],
            [InlineKeyboardButton(text="🗑️ Очистити корзину", callback_data="cart_clear")]
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(text=text, reply_markup=keyboard)
    else:
        text += "<i>🕳 Тут порожньо</i>"
        await message.answer(text=text)


@dp.callback_query(F.data == "cart_clear")
async def clear_cart_callback(call: CallbackQuery) -> None:
    user_id = call.from_user.id
    try:
        coll_users.update_one({"id":user_id}, {"$set":{"cart": {}}})
        await call.answer("🗑 Корзину очищено!")


        await call.message.edit_text(text="🛒 <b>Корзина</b>\n\n<i>🕳 Тут порожньо</i>")
    except Exception as e:
        await call.answer("⚠️ Помилка!")
        print(e)

async def get_last_payment_id():
    last = coll_payments.find_one(sort=[("_id", -1)])
    if last:
        return int(last['id'].split("_")[0])+1
    return 1

@dp.callback_query(F.data == "buy")
async def buy_callback(call: CallbackQuery) -> None:
    user_id = call.from_user.id
    user = coll_users.find_one({"id":user_id})
    cart = user["cart"]
    if cart:
        total_price = 0
        order_text = ""
        order_id = await get_last_payment_id()

        now = datetime.now(timezone.utc)
        expire = now + timedelta(minutes=5)
        expire_time = expire.strftime("%Y-%m-%d %H:%M:%S")

        for prod_id in list(cart.keys()):
            product = coll_products.find_one({"id": int(prod_id)})
            total_price += product["price"]*cart[prod_id]
            order_text += f"{product['emj']} {product['name']} – x{cart[prod_id]}\n"

        random_order_id = f"{order_id}_{random.randint(1, 999999)}"
        params = {
            'version': 3,
            'public_key': PUBLIC_KEY,
            'action': 'pay',
            'amount': total_price,
            'currency': 'UAH',
            'description': order_text,
            'order_id': random_order_id,
            'expired_date': expire_time,
            'sandbox': 1
        }
        data = liq.data_to_sign(params)
        sign = liq.str_to_sign(
            PRIVATE_KEY +
            data +
            PRIVATE_KEY
        )

        coll_payments.insert_one({"id": random_order_id,
                                  'user_id':user_id,
                                  'goods':cart,
                                  'price':total_price,
                                  'status':'Processing',
                                  "create_time": now,
                                  'finish_time': -1
                                  })

        payment_url = f"https://www.liqpay.ua/api/3/checkout/?data={data}&signature={sign}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💸 Оплатити", url=payment_url)]])

        await call.message.edit_text("Оплата доступна за кнопкою:", reply_markup=keyboard)
        await answer_payment(random_order_id, expire, call)
    else:
        await call.answer("🕳 Ваша корзина порожня")
        await call.message.edit_text("🛒 <b>Корзина</b>\n\n🕳 Тут порожньо")

async def answer_payment(order_id, expire_time, call):
    user_id = call.from_user.id
    message = call.message

    while datetime.now(timezone.utc) < expire_time:
        res = liq.api("request", {
            'public_key': PUBLIC_KEY,
            'action': 'status',
            'version': 3,
            'order_id': order_id
        })
        if res['result'] == 'ok':
            try:
                coll_payments.update_one({'id':order_id}, {"$set":{"status": "Success", "finish_time": datetime.now(timezone.utc)}})
                coll_users.update_one({"id":user_id}, {"$set":{"cart":{}}})

                total_price = res['amount']
                text = (f"✅ <b>Оплату завершено!</b>\n\n"
                        f"Придбано:\n{res['description']}\n"
                        f"Заплачено: {total_price} грн\n\n"
                        f"Дякуємо за покупку!")

                await message.answer(text=text)
            except Exception as e:
                await message.answer(text="Помилкла!")
                print(e)
            return
        await asyncio.sleep(2)

    coll_payments.update_one({'id': order_id},
                             {"$set": {"status": "Timeout", "finish_time": datetime.now(timezone.utc)}})
    await message.reply(text="⚠️ <b>Помилка оплати: час вичерпано!</b>")
    await message.edit_text(text="⌛️ Час оплати вичерпано:(")

if __name__ == '__main__':
    print("Running...")
    asyncio.run(dp.start_polling(bot))