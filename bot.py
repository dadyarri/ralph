"""
:project: ralph
:version: see VERSION.txt
:authors: dadyarri, 6a16ec
:contact: https://vk.me/dadyarri, https://vk.me/6a16ec
:license: MIT

:copyright: (c) 2019 - 2020 dadyarri, 6a16ec

Info about logging levels:

DEBUG: Detailed information, typically of interest only when diagnosing problems.

INFO: Confirmation that things are working as expected.

WARNING: An indication that something unexpected happened, or indicative of some
problem in the near future (e.g. ‘disk space low’). The software is still working
as expected.

ERROR: Due to a more serious problem, the software has not been able to perform
some function.

CRITICAL: A serious error, indicating that the program itself may be unable to
continue running.

"""

# TODO: Вытащить варианты режимов в enum`ы
# TODO: Вытащить вкшные методы в отдельный модуль


import json
import os
import random
from binascii import Error as binErr
from typing import List
from typing import NoReturn
from typing import Tuple

import gspread
import requests
import vk_api
from oauth2client.service_account import ServiceAccountCredentials
from vk_api.bot_longpoll import VkBotEventType

from keyboard import Keyboards
from logger import Logger
from vkbotlongpoll import RalphVkBotLongPoll


def auth(func):
    def wrapper(self):
        if not self.current_is_admin():
            self.send_gui(text="У тебя нет доступа к этой функции.")
        else:
            func(self)

    return wrapper


class Bot:
    """
    Класс, описывающий объект бота, включая авторизацию в API, и все методы бота.
    """

    def __init__(self) -> None:

        self.log = Logger()

        self.log.log.info("Инициализация...")

        self.token = os.environ["VK_TOKEN"]
        self.user_token = os.environ["VK_USER_TOKEN"]
        self.gid = os.environ["GID_ID"]
        self.cid = os.environ["CID_ID"]
        self.table = os.environ["TABLE_ID"]

        self.kbs = Keyboards()

        # Авторизация в API ВКонтакте
        self.log.log.info("Авторизация ВКонтакте...")
        try:
            self.bot_session = vk_api.VkApi(token=self.token, api_version="5.103")
            self.user_session = vk_api.VkApi(token=self.user_token, api_version="5.103")
        except vk_api.exceptions.AuthError:
            self.log.log.error("Неудача. Ошибка авторизации.")
        else:
            try:
                self.bot_vk = self.bot_session.get_api()
                self.user_vk = self.user_session.get_api()
                self.longpoll = RalphVkBotLongPoll(
                    vk=self.bot_session, group_id=self.gid
                )
            except requests.exceptions.ConnectionError:
                self.log.log.error("Неудача. Превышен лимит попыток подключения.")
            except vk_api.exceptions.ApiError:
                self.log.log.error("Неудача. Ошибка доступа.")
            else:
                self.log.log.info("Успех.")
                self.log.log.debug(
                    f"Версия API ВКонтакте: {self.bot_session.api_version}."
                )

        # Инициализация дополнительных переменных
        self.event = {}
        self.admins = os.environ["ADMINS_IDS"].split(",")

        # Переменные состояния сессии (для администраторов)
        self.col = 0

        # Авторизация в API Google Sheets и подключение к заданной таблице
        self.log.log.info("Авторизация в Google Cloud...")
        self.scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        try:
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(
                keyfile_dict=json.loads(os.environ["GOOGLE_CREDS"]), scopes=self.scope
            )
        except binErr:
            self.log.log.error("Неудача.")
        else:
            self.gc = gspread.authorize(credentials=credentials)
            self.table_auth = self.gc.open_by_key(key=self.table)
            self.sh = self.table_auth.get_worksheet(0)
            self.sh_sch = self.table_auth.get_worksheet(1)
            self.log.log.info("Успех.")

        # Переименование обрабатываемых типов событий
        self.NEW_MESSAGE = VkBotEventType.MESSAGE_NEW

        self.log.log.info(
            f"Беседа... {'Тестовая' if self.cid.endswith('1') else 'Основная'}"
        )

        self.log.log.info("Обновление версии в статусе группы...")
        try:
            with open("VERSION.txt", "r") as f:
                v = f"Версия: {f.read()}"
            self.user_vk.status.set(text=v, group_id=self.gid)
        except vk_api.exceptions.ApiError as e:
            self.log.log.error(f"Ошибка {e.__str__()}")
        else:
            self.log.log.info(f"Успех.")
        self.log.log.info("Инициализация завершена.")

    def send_message(
        self,
        msg: str,
        pid: int = None,
        keyboard: str = "",
        attachments: str = None,
        user_ids: str = None,
        forward: str = "",
    ) -> NoReturn:

        """
        Отправка сообщения msg пользователю/в беседу pid
        с клавиатурой keyboard (не отправляется, если не указан json файл)
        """

        try:
            self.bot_vk.messages.send(
                peer_id=pid,
                random_id=random.getrandbits(64),
                message=msg,
                keyboard=keyboard,
                attachments=attachments,
                user_ids=user_ids,
                forward_messages=forward,
            )

        except vk_api.exceptions.ApiError as e:
            self.log.log.error(msg=e.__str__())
        except FileNotFoundError as e:
            self.log.log.error(msg=e)

    def send_mailing(self, ids: str, msg: str = "") -> NoReturn:
        """
        Отправка рассылки
        """
        self.send_message(msg=msg, user_ids=ids)

    def _get_conversations_ids(self) -> list:
        """
        Получает идентификаторы пользователей последних 200 диалогов
        """
        q = self.bot_vk.messages.getConversations(
            offset=1, count=200, group_id=self.gid
        )
        _l = []
        for i in range(len(q["items"])):
            if q["items"][i]["conversation"]["can_write"]["allowed"]:
                _l.append(str(q["items"][i]["conversation"]["peer"]["id"]))
        return _l

    def _handle_table(self, col: int) -> Tuple[str, str, str]:
        """
        Обрабатывает гугл-таблицу и составляет кортеж с данными о должниках
        """
        men, cash, goal = None, None, None
        try:
            self.gc.login()
            debtor_ids = []
            for i in range(5, 38):
                if self.sh.cell(i, col).value != self.sh.cell(41, col).value:
                    debtor_ids.append(self.sh.cell(i, 3).value)
        except gspread.exceptions.APIError as e:
            self.log.log.error(
                f"[ERROR]: [{e.response.error.code}] – {e.response.error.message}"
            )
            self._handle_table(col)
        except (AttributeError, KeyError, ValueError):
            self.log.log.error("Херню ты натворил, Даня!")
        else:
            debtor_ids = ",".join(debtor_ids)
            men = self.generate_mentions(debtor_ids, True)
            cash = self.sh.cell(41, col).value
            goal = self.sh.cell(4, col).value
        if men is not None and cash is not None and goal is not None:
            return men, cash, goal
        else:
            self._handle_table(col)

    @auth
    def get_debtors(self):
        """
        Призывает должников
        """
        self.send_message(
            msg="Эта команда может работать медленно. Прошу немного подождать.",
            pid=self.event.object.from_id,
        )
        men, cash, goal = self._handle_table(self.col)
        msg = f"{men} вам нужно принести по {cash} на {goal.lower()}."
        self.send_message(msg=msg, pid=self.cid)
        self.send_gui(text="Команда успешно выполнена.")

    def _get_users_info(self, ids: list) -> List[dict]:
        """
        Получает информацию о пользователях с указанными id
        """
        return self.bot_vk.users.get(user_ids=",".join(map(str, ids)))

    def generate_mentions(self, ids: str, names: bool) -> str:
        """
        Генерирует строку с упоминаниями из списка идентификаторов
        """
        ids = list(filter(bool, ids.replace(" ", "").split(",")))
        users_info = self._get_users_info(ids)
        users_names = [
            users_info[i]["first_name"] if names else "!" for i in range(len(ids))
        ]
        result = (", " if names else "").join(
            [f"@id{_id}({users_names[i]})" for (i, _id) in enumerate(ids)]
        )
        return result

    def current_is_admin(self) -> bool:
        """
        Проверяет, является ли текущий пользователь администратором бота
        """
        return str(self.event.object.from_id) in self.admins

    def send_gui(self, text: str = "Привет!") -> NoReturn:
        """
        Отправляет клавиатуру в зависимости от статуса пользователя
        """
        self.send_message(
            msg=text,
            pid=self.event.object.from_id,
            keyboard=self.kbs.generate_main_menu(self.current_is_admin()),
        )

    def show_msg(self, text: str):
        self.send_message(
            msg=text, pid=self.event.object.from_id,
        )
