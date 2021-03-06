import datetime
import json
import os
import re
from enum import Enum
from typing import Tuple

import requests
from psycopg2 import ProgrammingError
from vk_api.bot_longpoll import VkBotEventType

from bot import Bot
from database import Database
from keyboard import Keyboards
from scheduler import Date
from scheduler import Schedule

db = Database(os.environ["DATABASE_URL"])
bot = Bot()
kbs = Keyboards()

bot.auth()
bot.update_version()


class EventTypes(Enum):
    NEW_MESSAGE = VkBotEventType.MESSAGE_NEW


def send_schedule(date: str):
    group = db.get_group_of_user(event["message"]["from_id"])
    gid = db.get_schedule_descriptor(group)
    s = Schedule(date, gid)
    s.get_raw()
    if s.is_exist():
        sch = s.generate()
        bot.send_message(msg=sch, pid=event["message"]["from_id"])
    else:
        bot.send_message(msg="Расписание отсутствует.", pid=event["message"]["from_id"])


def generate_call_message():
    f = db.get_names_using_status(event["message"]["from_id"])
    students_ids = db.get_call_ids(event["message"]["from_id"])
    if students_ids is not None:
        mentions = bot.generate_mentions(ids=students_ids, names=f)
    else:
        mentions = ""
    message = db.get_call_message(event["message"]["from_id"]) or ""
    message = f"{mentions}\n{message}"
    return message


def generate_debtors_message():
    f = db.get_names_using_status(event["message"]["from_id"])
    students_ids = db.get_call_ids(event["message"]["from_id"])
    slg = db.get_active_expenses_category(event["message"]["from_id"])
    nm = db.get_expense_category_by_slug(slg)
    sm = db.get_expense_summ(slg)
    if students_ids is not None:
        mentions = bot.generate_mentions(ids=students_ids, names=f)
    else:
        mentions = ""
    message = f"{mentions}, вам нужно принести по {sm} руб. на {nm}."
    return message


def send_call_confirm():
    chat_id = db.get_conversation(event["message"]["from_id"])
    if db.get_session_state(event["message"]["from_id"]) == "debtors_forming":
        message = generate_debtors_message()
    else:
        message = generate_call_message()
    atch = db.get_call_attaches(event["message"]["from_id"])
    if atch is None:
        atch = ""
    if message != "\n" or atch:
        bot.send_message(
            msg=f"В {'основную ' if chat_id else 'тестовую '}"
            f"беседу будет отправлено сообщение:",
            pid=event["message"]["from_id"],
            keyboard=kbs.prompt(event["message"]["from_id"]),
        )
        bot.send_message(msg=message, pid=event["message"]["from_id"], attachment=atch)
    else:
        db.empty_call_storage(event["message"]["from_id"])
        bot.send_gui(
            pid=event["message"]["from_id"],
            text="Сообщение не может быть пустым. Отмена...",
        )


def load_attachs():
    attachments = []
    for i, v in enumerate(event["message"]["attachments"]):
        m = -1
        m_url = ""
        for ind, val in enumerate(event["message"]["attachments"][i]["photo"]["sizes"]):
            if val["height"] > m:
                m_url = val["url"]
        req = requests.get(m_url)
        server = bot.bot_vk.photos.getMessagesUploadServer()
        with open(f"photo.jpg", "wb") as f:
            f.write(req.content)
        file = open(f"photo.jpg", "rb")
        upload = requests.post(server["upload_url"], files={"photo": file},).json()
        save = bot.bot_vk.photos.saveMessagesPhoto(**upload)
        photo = f"photo{save[0]['owner_id']}_{save[0]['id']}"
        attachments.append(photo)
    atch = ",".join(attachments)
    state = db.get_session_state(event["message"]["from_id"])
    if state == "ask_for_mailing_message":
        db.update_mailing_attaches(event["message"]["from_id"], atch)
    elif state == "ask_for_call_message":
        db.update_call_attaches(event["message"]["from_id"], atch)


def invite_bot():
    """Срабатывает, если текущее событие - приглашение бота в беседу
    """
    try:
        if event["message"]["action"][
            "type"
        ] == "chat_invite_user" and event.object.message["action"]["member_id"] == -int(
            bot.gid
        ):
            if (
                event.objects.message["peer_id"] not in db.get_cached_chats()
                and event.objects.message["peer_id"] not in db.get_registered_chats()
            ):
                db.add_cached_chat(event.objects.message["peer_id"])
            bot.send_message(
                msg="Привет! Для полноценной работы меня нужно сделать администратором",
                pid=event.object.message["peer_id"],
            )
    except (KeyError, TypeError):
        pass


for event in bot.longpoll.listen():
    event = {
        "type": event.type,
        "client_info": event.object.client_info,
        "message": event.object.message,
    }

    invite_bot()

    if (
        event["type"] == EventTypes.NEW_MESSAGE.value
        and (event["message"]["text"] or event["message"]["attachments"])
        and event["message"]["out"] == 0
        and event["message"]["from_id"] == event["message"]["peer_id"]
    ):
        try:
            payload = json.loads(event["message"]["payload"])
        except KeyError:
            payload = {"button": ""}
        text = event["message"]["text"].lower()

        # :blockstart: Запуск интерфейса
        if text in ["начать", "старт", "r"]:
            if not db.is_user_exist(event["message"]["from_id"]):
                db.create_user(event["message"]["from_id"])
            if not db.is_session_exist(event["message"]["from_id"]):
                db.create_session(event["message"]["from_id"])
            bot.send_gui(pid=event["message"]["from_id"])
        # :blockend: Запуск интерфейса

        # :blockstart: Возврат на главный экран
        elif payload["button"] == "home":
            bot.send_gui(text="Главный экран", pid=event["message"]["from_id"])
        # :blockend: Возврат на главный экран

        # :blockstart: Призыв
        elif payload["button"] == "call":
            db.update_session_state(event["message"]["from_id"], "ask_for_call_message")
            if not db.call_session_exist(event["message"]["from_id"]):
                db.create_call_session(event["message"]["from_id"])
            bot.send_message(
                msg="Отправьте сообщение к призыву (есть поддержка изображений)",
                pid=event["message"]["from_id"],
                keyboard=kbs.skip(),
            )
        elif payload["button"] == "letter":
            group = db.get_group_of_user(event["message"]["from_id"])
            bot.send_message(
                msg=f"Отправка клавиатуры с фамилиями на букву \"{payload['letter']}\"",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_names_keyboard(payload["letter"], group),
            )
        elif (
            payload["button"] == "student"
            and db.get_session_state(event["message"]["from_id"]) != "select_donater"
        ):
            ids = db.get_call_ids(event["message"]["from_id"])
            if ids:
                students = ids.split(",")
            else:
                students = [ids]
            if str(db.get_vk_id(payload["id"])) in students:
                bot.send_message(
                    msg=f"{payload['name']} уже был выбран для призыва. Пропуск.",
                    pid=event["message"]["from_id"],
                )
            else:
                db.append_to_call_ids(
                    event["message"]["from_id"], db.get_vk_id(payload["id"])
                )
                bot.send_message(
                    msg=f"{payload['name']} добавлен к списку призыва.",
                    pid=event["message"]["from_id"],
                )
        elif (
            payload["button"] == "back"
            and db.get_session_state(event["message"]["from_id"]) != "select_donater"
        ):
            group = db.get_group_of_user(event["message"]["from_id"])
            bot.send_message(
                msg="Отправка клавиатуры с алфавитом.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_call_prompt(group),
            )
        elif payload["button"] == "skip":
            db.update_session_state(event["message"]["from_id"], "call_configuring")
            group = db.get_group_of_user(event["message"]["from_id"])
            bot.send_message(
                msg="Отправка клавиатуры с алфавитом.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_call_prompt(group),
            )
        elif (
            db.get_session_state(event["message"]["from_id"]) == "ask_for_call_message"
        ):
            db.update_call_message(
                event["message"]["from_id"], event["message"]["text"]
            )
            if event["message"]["attachments"]:
                load_attachs()
            group = db.get_group_of_user(event["message"]["from_id"])
            bot.send_message(
                msg="Отправка клавиатуры призыва",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_call_prompt(group),
            )
            db.update_session_state(event["message"]["from_id"], "call_configuring")
        elif payload["button"] == "send_to_all":
            group = db.get_group_of_user(event["message"]["from_id"])
            ids = ",".join(db.get_active_students_ids(group))
            db.update_call_ids(event["message"]["from_id"], ids)
            bot.send_message(
                msg="Все студенты отмечены как получатели уведомления",
                pid=event["message"]["from_id"],
            )
            send_call_confirm()
        elif payload["button"] == "save":
            send_call_confirm()
        elif (
            payload["button"] == "cancel"
            and db.get_session_state(event["message"]["from_id"]) == "call_configuring"
        ):
            db.empty_call_storage(event["message"]["from_id"])
            db.update_session_state(event["message"]["from_id"], "main")
            bot.send_gui(
                text="Выполнение команды отменено.", pid=event["message"]["from_id"]
            )
        elif payload["button"] == "confirm" and db.get_session_state(
            event["message"]["from_id"]
        ) in ["call_configuring", "debtors_forming"]:
            bot.log.info("Отправка призыва...")
            chat_type = db.get_conversation(event["message"]["from_id"])
            group = db.get_group_of_user(event["message"]["from_id"])
            cid = db.get_chat_id(group, chat_type)
            if db.get_session_state(event["message"]["from_id"]) == "debtors_forming":
                text = generate_debtors_message()
            else:
                text = generate_call_message()
            attachment = db.get_call_attaches(event["message"]["from_id"])
            if attachment is None:
                attachment = ""
            bot.send_message(pid=cid, msg=text, attachment=attachment)
            db.empty_call_storage(event["message"]["from_id"])
            db.update_session_state(event["message"]["from_id"], "main")
            bot.send_gui(text="Сообщение отправлено.", pid=event["message"]["from_id"])
        elif payload["button"] == "deny" and db.get_session_state(
            event["message"]["from_id"]
        ) in ["call_configuring", "debtors_forming"]:
            db.update_call_message(event["message"]["from_id"], " ")
            db.update_call_ids(event["message"]["from_id"], " ")
            db.update_session_state(event["message"]["from_id"], "main")
            bot.send_gui(
                text="Выполнение команды отменено.", pid=event["message"]["from_id"]
            )
        elif payload["button"] == "chconv_call":
            conv = db.get_conversation(event["message"]["from_id"])
            if conv == 0:
                db.update_conversation(event["message"]["from_id"], 1)
                chat = 2
            elif conv == 1:
                db.update_conversation(event["message"]["from_id"], 0)
                chat = 1
            send_call_confirm()

        elif payload["button"] == "chnames_call":
            if db.get_names_using_status(event["message"]["from_id"]):
                status = 0
            else:
                status = 1
            db.update_names_using_status(event["message"]["from_id"], status)
            send_call_confirm()
        # :blockend: Призыв

        # :blockstart: Расписание
        elif payload["button"] == "schedule":
            bot.send_message(
                msg="Отправка клавиатуры с расписанием.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_schedule_keyboard(),
            )
        elif payload["button"] == "today":
            d = Date()
            send_schedule(d.today)
        elif payload["button"] == "tomorrow":
            d = Date()
            send_schedule(d.tomorrow)
        elif payload["button"] == "day_after_tomorrow":
            d = Date()
            send_schedule(d.day_after_tomorrow)
        elif payload["button"] == "arbitrary":
            bot.send_message(
                msg="Напишите дату в формате ДД-ММ-ГГГГ.",
                pid=event["message"]["from_id"],
                keyboard=kbs.cancel(),
            )
            db.update_session_state(
                event["message"]["from_id"], "ask_for_schedule_date"
            )
        elif (
            payload["button"] == "cancel"
            and db.get_session_state(event["message"]["from_id"])
            == "ask_for_schedule_date"
        ):
            db.update_session_state(event["message"]["from_id"], "main")
            bot.send_message(
                msg="Выполнение команды отменено.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_schedule_keyboard(),
            )
        elif (
            db.get_session_state(event["message"]["from_id"]) == "ask_for_schedule_date"
        ):
            if re.match(r"^\d\d(.|-|/)\d\d(.|-|/)20\d\d$", event["message"]["text"]):
                try:
                    d = datetime.datetime.strptime(
                        event["message"]["text"], "%d-%m-%Y"
                    ).strftime("%Y-%m-%d")
                except ValueError:
                    bot.send_message(
                        msg="Неверный формат даты. Попробуйте еще раз.",
                        pid=event["message"]["from_id"],
                    )
                else:
                    group = db.get_group_of_user(event["message"]["from_id"])
                    s = Schedule(d, group)
                    s.get_raw()
                    if s.is_exist():
                        schedule = s.generate()
                        bot.send_message(
                            msg=schedule,
                            pid=event["message"]["from_id"],
                            keyboard=kbs.generate_schedule_keyboard(),
                        )
                        db.update_session_state(event["message"]["from_id"], "main")
                    else:
                        bot.send_message(
                            msg="Расписание отсутствует.\nПопробуй указать другую "
                            "дату.",
                            pid=event["message"]["from_id"],
                        )
                        db.update_session_state(
                            event["message"]["from_id"], "ask_for_schedule_date"
                        )
            else:
                bot.send_message(
                    msg="Неверный формат даты. Попробуйте еще раз.",
                    pid=event["message"]["from_id"],
                )
        # :blockend: Расписание

        # :blockstart: Рассылки
        elif payload["button"] == "mailings":
            group = db.get_group_of_user(event["message"]["from_id"])
            bot.send_message(
                msg="Отправка клавиатуры со списком рассылок.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_mailings_keyboard(group),
            )
        elif payload["button"] == "mailing":
            if not db.mailing_session_exist(event["message"]["from_id"]):
                db.create_mailing_session(event["message"]["from_id"])
            db.update_mailing_session(event["message"]["from_id"], payload["id"])
            bot.send_message(
                msg=f"Меню управления рассылкой \"{payload['name']}\":",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_mailing_mgmt(
                    is_admin=bot.is_admin(event["message"]["from_id"]),
                    m_id=payload["id"],
                    user_id=event["message"]["from_id"],
                ),
            )
        elif payload["button"] == "subscribe":
            u_id = db.get_user_id(payload["user_id"])
            db.update_subscribe_state(payload["slug"], u_id, 1)
            bot.send_message(
                msg="Вы были успешно подписаны на рассылку.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_mailing_mgmt(
                    is_admin=bot.is_admin(event["message"]["from_id"]),
                    m_id=payload["id"],
                    user_id=event["message"]["from_id"],
                ),
            )
        elif payload["button"] == "unsubscribe":
            u_id = db.get_user_id(payload["user_id"])
            db.update_subscribe_state(payload["slug"], u_id, 0)
            bot.send_message(
                msg="Вы были успешно отписаны от рассылки.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_mailing_mgmt(
                    is_admin=bot.is_admin(event["message"]["from_id"]),
                    m_id=payload["id"],
                    user_id=event["message"]["from_id"],
                ),
            )
        elif payload["button"] == "inline_unsubscribe":
            u_id = db.get_user_id(payload["user_id"])
            db.update_subscribe_state(payload["slug"], u_id, 0)
            bot.send_message(
                msg="Вы были успешно отписаны от рассылки.",
                pid=event["message"]["from_id"],
            )
        elif payload["button"] == "send_mailing":
            db.update_session_state(
                event["message"]["from_id"], "ask_for_mailing_message"
            )
            bot.send_message(
                msg="Отправьте текст рассылки (есть поддержка изображений)",
                pid=event["message"]["from_id"],
                keyboard=kbs.cancel(),
            )
        elif (
            payload["button"] == "cancel"
            and db.get_session_state(event["message"]["from_id"])
            == "ask_for_mailing_message"
        ):
            bot.send_message(
                msg="Выполнение команды отменено. Возвращаюсь на экран управления "
                "рассылкой.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_mailing_mgmt(
                    is_admin=bot.is_admin(event["message"]["from_id"]),
                    m_id=db.get_mailing_session(event["message"]["from_id"]),
                    user_id=event["message"]["from_id"],
                ),
            )
            db.update_session_state(event["message"]["from_id"], "main")
        elif (
            db.get_session_state(event["message"]["from_id"])
            == "ask_for_mailing_message"
        ):
            db.update_mailing_message(
                event["message"]["from_id"], event["message"]["text"]
            )
            if event["message"]["attachments"]:
                load_attachs()
            bot.send_message(
                msg="Всем подписчикам рассылки будет отправлено сообщение с указанным вами текстом",
                pid=event["message"]["from_id"],
                keyboard=kbs.prompt(),
                forward=f"{event['message']['id']}",
            )
            db.update_session_state(event["message"]["from_id"], "prompt_mailing")
        elif (
            payload["button"] == "confirm"
            and db.get_session_state(event["message"]["from_id"]) == "prompt_mailing"
        ):
            group = db.get_group_of_user(event["message"]["from_id"])
            attach = db.get_mailing_attaches(event["message"]["from_id"])
            if attach is None:
                attach = ""
            bot.send_mailing(
                m_id=db.get_mailing_session(event["message"]["from_id"]),
                text=db.get_mailing_message(event["message"]["from_id"]),
                attach=attach,
                group=group,
            )
            db.update_mailing_message(event["message"]["from_id"], "")
            db.update_mailing_attaches(event["message"]["from_id"], "")
            bot.send_message(
                msg="Рассылка отправлена.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_mailings_keyboard(group),
            )
        elif (
            payload["button"] == "deny"
            and db.get_session_state(event["message"]["from_id"]) == "prompt_mailing"
        ):
            group = db.get_group_of_user(event["message"]["from_id"])
            db.empty_mailing_storage(event["message"]["from_id"])
            bot.send_message(
                msg="Отправка рассылки отменена.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_mailings_keyboard(group),
            )
        # :blockend: Рассылки

        # :blockstart: Параметры
        elif payload["button"] == "prefs":
            bot.send_message(
                msg="Параметры",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_prefs_keyboard(),
            )
        elif payload["button"] == "names":
            status = db.get_names_using_status(event["message"]["from_id"])
            msg = (
                f"Использование имён в призыве "
                f"{'активно' if status else 'неактивно'}."
            )
            bot.send_message(
                msg=msg,
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_names_selector(status),
            )

        elif payload["button"] == "off_using_names":
            status = 0
            db.update_names_using_status(event["message"]["from_id"], status)
            bot.send_message(
                msg="Использование имён в призыве отключено.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_names_selector(bool(status)),
            )
        elif payload["button"] == "on_using_names":
            status = 1
            db.update_names_using_status(event["message"]["from_id"], status)
            bot.send_message(
                msg="Использование имён в призыве включено.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_names_selector(bool(status)),
            )

        elif payload["button"] == "chats":
            bot.send_message(
                msg="Настройки чатов",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_chat_prefs(),
            )

        elif payload["button"] == "local_chat":
            chat = db.get_conversation(event["message"]["from_id"])
            bot.send_message(
                msg="Локальная настройка чатов",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_local_chat_prefs(chat),
            )

        elif payload["button"] == "activate_test_chat":
            chat = db.update_conversation(event["message"]["from_id"], 0)
            bot.send_message(
                msg="Тестовая беседа активирована",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_local_chat_prefs(chat),
            )

        elif payload["button"] == "activate_main_chat":
            chat = db.update_conversation(event["message"]["from_id"], 1)
            bot.send_message(
                msg="Основная беседа активирована",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_local_chat_prefs(chat),
            )

        elif payload["button"] == "global_chat":
            group = db.get_group_of_user(event["message"]["from_id"])

            bot.send_message(
                msg="Глобальная настройка чатов",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_global_chat_prefs(group),
            )

        elif payload["button"] == "configure_chat":
            chat = bot.bot_vk.messages.getConversationsById(
                peer_ids=payload["chat_id"], group_id=bot.gid
            )
            status = ""
            if not chat["items"]:
                status = (
                    "Бот не администратор в этом чате. Это может мешать "
                    "корректной работе"
                )
            if payload["chat_type"]:
                chat_type = "основного"
            else:
                chat_type = "тестового"
            bot.send_message(
                msg=f"Настройки {chat_type} чата\n{status}",
                pid=event["message"]["from_id"],
                keyboard=kbs.configure_chat(
                    payload["group"], payload["chat_type"], payload["chat_id"]
                ),
            )

        elif payload["button"] == "reg_chat":
            chats: Tuple[int] = db.get_cached_chats()
            chats_info: str = bot.bot_vk.messages.getConversationsById(
                peer_ids=",".join(map(str, chats)), group_id=bot.gid
            )
            bot.send_message(
                msg="Выберите чат для регистрации\n(Если вы видите кнопки в названии "
                "которых вопросительные знаки, значит в этом чате бот не является администратором,"
                "что недопустимо для нормальной работы бота. Проверьте права доступа и вернитесь)",
                pid=event["message"]["from_id"],
                keyboard=kbs.reg_chat(chats, chats_info),
            )

        elif payload["button"] == "add_chat":
            group = db.get_group_of_user(event["message"]["from_id"])
            bot.send_message(
                msg="Выберите тип регистрируемого чата",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_available_chat_types(payload["chat_id"], group),
            )

        elif payload["button"] == "reg_as_main":
            group = db.get_group_of_user(event["message"]["from_id"])
            db.remove_cached_chat(payload["chat_id"])
            db.registrate_chat(payload["chat_id"], 1, group)
            bot.send_message(
                msg="Чат зарегистрирован как основной",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_global_chat_prefs(group),
            )

        elif payload["button"] == "reg_as_test":
            group = db.get_group_of_user(event["message"]["from_id"])
            db.remove_cached_chat(payload["chat_id"])
            db.registrate_chat(payload["chat_id"], 0, group)
            bot.send_message(
                msg="Чат зарегистрирован как тестовый",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_global_chat_prefs(group),
            )

        elif payload["button"] == "activate_chat":
            if payload["chat_type"]:
                db.update_chat_activity(payload["group"], 1, 1)
                db.update_chat_activity(payload["group"], 0, 0)
                chat_type = "Основной"
            else:
                db.update_chat_activity(payload["group"], 1, 0)
                db.update_chat_activity(payload["group"], 0, 1)
                chat_type = "Тестовый"
            bot.send_message(
                msg=f"{chat_type} чат выбран для отправки рассылок",
                pid=event["message"]["from_id"],
                keyboard=kbs.configure_chat(
                    payload["group"], payload["chat_type"], payload["chat_id"]
                ),
            )

        elif payload["button"] == "unpin_chat":
            db.unpin_chat(payload["group"], payload["chat_type"])
            db.add_cached_chat(payload["chat_id"])
            bot.send_message(
                msg="Чат откреплен",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_global_chat_prefs(payload["group"]),
            )

        # :blockend: Параметры

        # :blockstart: Финансы

        elif payload["button"] == "finances":
            group = db.get_group_of_user(event["message"]["from_id"])
            bot.send_message(
                msg="Меню финансов",
                pid=event["message"]["from_id"],
                keyboard=kbs.finances_main(group),
            )

        elif payload["button"] == "fin_category":
            if "id" not in payload and "name" not in payload:
                e_id = db.get_active_expenses_category(event["message"]["from_id"])
                payload.update(
                    {"id": e_id, "name": db.get_expense_category_by_slug(e_id),}
                )
            db.update_active_expenses_category(
                event["message"]["from_id"], payload["id"]
            )
            bot.send_message(
                msg=f"Меню управления статьей {payload['name']}.",
                pid=event["message"]["from_id"],
                keyboard=kbs.fin_category_menu(),
            )

        elif payload["button"] == "balance":
            donates = sum(db.get_all_donates())
            expenses = sum(db.get_all_expenses())
            delta = donates - expenses

            bot.send_message(
                msg=f"Остаток: {delta} руб.", pid=event["message"]["from_id"]
            )
        elif payload["button"] == "add_expense_cat":
            db.update_session_state(
                user_id=event["message"]["from_id"],
                state="ask_for_new_expenses_cat_prefs",
            )
            bot.send_message(
                msg="Отправьте название статьи расхода и сумму сбора, отделенную "
                "запятой.\n Пример: 23 февраля, 500",
                pid=event["message"]["from_id"],
                keyboard=kbs.cancel(),
            )
        elif (
            db.get_session_state(event["message"]["from_id"])
            == "ask_for_new_expenses_cat_prefs"
            and payload["button"] == "cancel"
        ):
            group = db.get_group_of_user(event["message"]["from_id"])
            db.update_session_state(event["message"]["from_id"], "main")
            bot.send_message(
                msg="Операция отменена.",
                pid=event["message"]["from_id"],
                keyboard=kbs.finances_main(group),
            )
        elif (
            db.get_session_state(event["message"]["from_id"])
            == "ask_for_new_expenses_cat_prefs"
        ):
            if re.match(r"^.*,.*\d+$", event["message"]["text"]):
                parsed = event["message"]["text"].split(",")
                name, summ = parsed
                group = db.get_group_of_user(event["message"]["from_id"])
                db.add_expences_category(name, summ, group)
                bot.send_message(
                    msg=f'Новая статья "{name}" с суммой сборов {summ} р. успешно создана.',
                    pid=event["message"]["from_id"],
                    keyboard=kbs.finances_main(group),
                )
                db.update_session_state(event["message"]["from_id"], "main")
            else:
                group = db.get_group_of_user(event["message"]["from_id"])
                bot.send_message(
                    msg=f"Неверный формат сообщения.",
                    pid=event["message"]["from_id"],
                    keyboard=kbs.finances_main(group),
                )

        elif payload["button"] == "fin_prefs":
            cat = db.get_expense_category_by_slug(
                db.get_active_expenses_category(event["message"]["from_id"])
            )
            bot.send_message(
                msg=f"Настройки категории {cat}",
                pid=event["message"]["from_id"],
                keyboard=kbs.fin_prefs(),
            )

        elif payload["button"] == "update_summ":
            cat = db.get_expense_category_by_slug(
                db.get_active_expenses_category(event["message"]["from_id"])
            )
            db.update_session_state(
                user_id=event["message"]["from_id"], state="ask_for_expense_cat_summ",
            )
            bot.send_message(
                msg=f"Введите новую сумму для статьи {cat}:",
                pid=event["message"]["from_id"],
                keyboard=kbs.cancel(),
            )

        elif (
            payload["button"] == ""
            and db.get_session_state(event["message"]["from_id"])
            == "ask_for_expense_cat_summ"
        ):
            if re.match(r"^\d+$", event["message"]["text"]):
                db.update_expense_summ(
                    db.get_active_expenses_category(event["message"]["from_id"]),
                    event["message"]["text"],
                )
                bot.send_message(
                    msg="Сумма сборов обновлена.",
                    pid=event["message"]["from_id"],
                    keyboard=kbs.fin_prefs(),
                )
            else:
                bot.send_message(
                    msg="Неверный формат сообщения. Необходимо только число.",
                    pid=event["message"]["from_id"],
                )

        elif (
            payload["button"] == "cancel"
            and db.get_session_state(event["message"]["from_id"])
            == "ask_for_expense_cat_summ"
        ):
            db.update_session_state(event["message"]["from_id"], "main")
            bot.send_message(
                msg="Операция отменена.",
                pid=event["message"]["from_id"],
                keyboard=kbs.fin_category_menu(),
            )

        elif payload["button"] == "update_name":
            cat = db.get_expense_category_by_slug(
                db.get_active_expenses_category(event["message"]["from_id"])
            )
            db.update_session_state(
                user_id=event["message"]["from_id"], state="ask_for_expense_cat_name",
            )
            bot.send_message(
                msg=f"Введите новое имя для статьи {cat}:",
                pid=event["message"]["from_id"],
                keyboard=kbs.cancel(),
            )

        elif (
            payload["button"] == ""
            and db.get_session_state(event["message"]["from_id"])
            == "ask_for_expense_cat_name"
        ):
            db.update_expense_name(
                db.get_active_expenses_category(event["message"]["from_id"]),
                event["message"]["text"],
            )
            bot.send_message(
                msg="Название сбора обновлено.",
                pid=event["message"]["from_id"],
                keyboard=kbs.fin_prefs(),
            )

        elif (
            payload["button"] == "cancel"
            and db.get_session_state(event["message"]["from_id"])
            == "ask_for_expense_cat_name"
        ):
            db.update_session_state(event["message"]["from_id"], "main")
            bot.send_message(
                msg="Операция отменена.",
                pid=event["message"]["from_id"],
                keyboard=kbs.fin_category_menu(),
            )
        elif payload["button"] == "delete_expense":
            cat = db.get_expense_category_by_slug(
                db.get_active_expenses_category(event["message"]["from_id"])
            )
            db.update_session_state(
                user_id=event["message"]["from_id"], state="confirm_delete_expense",
            )
            bot.send_message(
                msg=f"Вы действительно хотите удалить статью {cat}?\nВсе связанные "
                f"записи также будут удалены.",
                pid=event["message"]["from_id"],
                keyboard=kbs.prompt(),
            )

        elif (
            payload["button"] == "confirm"
            and db.get_session_state(event["message"]["from_id"])
            == "confirm_delete_expense"
        ):
            exp_id = db.get_active_expenses_category(event["message"]["from_id"])
            name = db.get_expense_category_by_slug(exp_id)
            db.delete_expense_catgory(exp_id)
            db.update_active_expenses_category(event["message"]["from_id"], "none")
            db.update_session_state(event["message"]["from_id"], "main")
            group = db.get_group_of_user(event["message"]["from_id"])
            bot.send_message(
                msg=f"Категория {name} удалена.",
                pid=event["message"]["from_id"],
                keyboard=kbs.finances_main(group),
            )

        elif (
            payload["button"] == "deny"
            and db.get_session_state(event["message"]["from_id"])
            == "confirm_delete_expense"
        ):
            db.update_session_state(event["message"]["from_id"], "main")
            bot.send_message(
                msg="Операция отменена.",
                pid=event["message"]["from_id"],
                keyboard=kbs.fin_prefs(),
            )

        elif payload["button"] == "add_donate":
            try:
                db.update_session_state(event["message"]["from_id"], "select_donater")
            except ProgrammingError:
                pass
            group = db.get_group_of_user(event["message"]["from_id"])
            bot.send_message(
                msg="Выберите внесшего деньги:",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_finances_prompt(group),
            )

        elif (
            payload["button"] == "student"
            and db.get_session_state(event["message"]["from_id"]) == "select_donater"
        ):
            exp_id = db.get_active_expenses_category(event["message"]["from_id"])
            summ = db.get_expense_summ(exp_id)
            d_list = db.get_list_of_donaters_by_slug(exp_id)
            if payload["id"] in d_list:
                d_id = db.get_id_of_donate_record(payload["id"], exp_id)
                db.set_current_date_as_update(d_id)
            else:
                d_id = db.create_donate(payload["id"], exp_id)
            db.update_donate_id(event["message"]["from_id"], d_id)
            db.update_session_state(event["message"]["from_id"], "ask_for_donate_summ")
            bot.send_message(
                msg="Введите сумму взноса",
                pid=event["message"]["from_id"],
                keyboard=kbs.cancel(),
            )

        elif (
            payload["button"] == "cancel"
            and db.get_session_state(event["message"]["from_id"])
            == "ask_for_donate_summ"
        ):
            d_id = db.get_donate_id(event["message"]["from_id"])
            db.delete_donate(d_id)
            bot.send_message(
                msg="Операция отменена.",
                pid=event["message"]["from_id"],
                keyboard=kbs.fin_category_menu(),
            )

        elif (
            payload["button"] == ""
            and db.get_session_state(event["message"]["from_id"])
            == "ask_for_donate_summ"
        ):
            if re.match(r"^\d+$", event["message"]["text"]):
                d_id = db.get_donate_id(event["message"]["from_id"])

                db.append_summ_to_donate(d_id, int(event["message"]["text"]))
                db.update_session_state(event["message"]["from_id"], "main")
                bot.send_message(
                    "Запись успешно создана.",
                    pid=event["message"]["from_id"],
                    keyboard=kbs.fin_category_menu(),
                )

            else:
                bot.send_message(
                    "Неверный формат сообщения. Необходимо только число.",
                    pid=event["message"]["from_id"],
                )

        elif (
            payload["button"] == "back"
            and db.get_session_state(event["message"]["from_id"]) == "select_donater"
        ):
            group = db.get_group_of_user(event["message"]["from_id"])
            bot.send_message(
                msg="Отправка клавиатуры с алфавитом.",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_finances_prompt(group),
            )

        elif (
            payload["button"] == "cancel"
            and db.get_session_state(event["message"]["from_id"]) == "select_donater"
        ):
            bot.send_message(
                msg="Операция отменена",
                pid=event["message"]["from_id"],
                keyboard=kbs.fin_category_menu(),
            )

        elif payload["button"] == "fin_stat":

            bot.send_message(msg="Вычисляю...", pid=event["message"]["from_id"])

            group = db.get_group_of_user(event["message"]["from_id"])
            exp_id = db.get_active_expenses_category(event["message"]["from_id"])
            wasted = sum(db.get_all_expenses_in_category(exp_id))
            summ = db.get_expense_summ(exp_id)
            d_ids = db.get_list_of_donaters_by_slug(exp_id, summ)
            s_ids = db.get_active_students_ids(group)
            name = db.get_expense_category_by_slug(exp_id)

            donated = len(d_ids)
            not_donated = len(s_ids) - donated
            collected = sum(db.get_all_donates_in_category(exp_id))

            bot.send_message(
                msg=f'Статистика по статье "{name}":\n'
                f"Всего сдали: {donated} человек;\n"
                f"Всего не сдали: {not_donated} человек;\n"
                f"Всего собрано: {collected} руб.\n"
                f"Всего потрачено: {wasted} руб.",
                pid=event["message"]["from_id"],
            )

        elif payload["button"] == "add_expense":
            db.update_session_state(event["message"]["from_id"], "ask_for_expense_summ")
            bot.send_message(
                msg="Введите сумму расхода (нужно ввести только число):",
                pid=event["message"]["from_id"],
                keyboard=kbs.cancel(),
            )

        elif (
            payload["button"] == "cancel"
            and db.get_session_state(event["message"]["from_id"])
            == "ask_for_expense_summ"
        ):
            db.update_session_state(event["message"]["from_id"], "main")
            bot.send_message(
                msg="Операция отменена.",
                pid=event["message"]["from_id"],
                keyboard=kbs.fin_category_menu(),
            )

        elif (
            db.get_session_state(event["message"]["from_id"]) == "ask_for_expense_summ"
        ):
            if re.match(r"^\d+$", event["message"]["text"]):
                exp_id = db.get_active_expenses_category(event["message"]["from_id"])
                db.add_expense(exp_id, event["message"]["text"])
                bot.send_message(
                    msg="Запись создана.",
                    pid=event["message"]["from_id"],
                    keyboard=kbs.fin_category_menu(),
                )
                db.update_session_state(event["message"]["from_id"], "main")

            else:
                bot.send_message(
                    msg="Неверный формат сообщения.", pid=event["message"]["from_id"]
                )

        elif payload["button"] == "debtors":
            bot.send_message(
                msg="Генерация сообщения может занять некоторое время...",
                pid=event["message"]["from_id"],
            )
            db.update_session_state(event["message"]["from_id"], "debtors_forming")
            exp_id = db.get_active_expenses_category(event["message"]["from_id"])
            summ = db.get_expense_summ(exp_id)
            d_s_ids = db.get_list_of_donaters_by_slug(exp_id, summ)
            d_ids = set([str(db.get_vk_id(i)) for i in d_s_ids])
            group = db.get_group_of_user(event["message"]["from_id"])
            s_ids = set(db.get_active_students_ids(group))
            debtors = ",".join(s_ids.difference(d_ids))
            db.update_call_ids(event["message"]["from_id"], debtors)
            send_call_confirm()

        # :blockend: Финансы

        # :blockstart: Веб-интерфейс

        elif payload["button"] == "web":
            bot.send_message(
                msg="Выберите группу для получения ссылки авторизации",
                pid=event["message"]["from_id"],
                keyboard=kbs.generate_administrating_groups(
                    event["message"]["from_id"]
                ),
            )

        elif payload["button"] == "get_auth_link":
            domain = "https://ralph-cms.herokuapp.com"
            url = domain + f"/api/auth/{payload['group']}"
            request = requests.get(url)
            if request.status_code == 200:
                arg = request.json()["result"]["link"]
                bot.send_message(
                    msg="Ваша одноразовая ссылка для авторизации под именем "
                    f"администратора группы {payload['group']}:\n"
                    f"{domain + arg}\nОна действительна в течении 5 минут.\nТак как "
                    f"панель управления находится на бесплатном хостинге, "
                    f"при открытии ссылки с компьютера могут возникнуть "
                    f"проблемы\nПохоже, (без костылей) это никак не решается.",
                    pid=event["message"]["from_id"],
                    keyboard=kbs.generate_main_menu(
                        bot.is_admin(event["message"]["from_id"])
                    ),
                )

        # :blockend: Веб-интерфейс
