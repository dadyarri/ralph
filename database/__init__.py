from database.base import Base


class Database(Base):
    """
        Класс для методов работы с БД, выполняющих конечную цель
    """

    def get_last_names_letters(self):
        """
        Получает из базы данных все уникальные первые буквы фамилий
        """
        letters = self.query(
            "SELECT DISTINCT substring(second_name from  '^.') FROM users_info "
            "ORDER BY substring(second_name from  '^.')"
        )
        return [letter for (letter,) in letters]

    def get_list_of_names(self, letter):
        """
        Получает из базы данных все фамилии, начинающиеся на букву
        """
        names = self.query(
            f"SELECT user_id, first_name, second_name FROM users_info "
            f"WHERE substring(second_name from '^.') = '{letter}' "
            f"AND academic_status > 0 ORDER BY user_id"
        )
        return names

    def get_vk_id(self, _id):
        """
        Получает из базы данных идентификатор ВКонтакте по идентификатору студента
        """
        vk_id = self.query(f"SELECT vk_id from users WHERE id={_id}")[0][0]
        return vk_id

    def get_user_id(self, vk_id):
        """
        Получает из базы данных идентификатор студента по идентификатору ВКонтакте
        """
        user_id = self.query(f"SELECT id from users WHERE vk_id={vk_id}")[0][0]
        return user_id

    def get_mailings_list(self):
        """
        Получает из базы данных весь список доступных рассылок
        """
        mailings = self.query(
            "SELECT mailing_id, mailing_name, mailing_slug from mailings"
        )
        return mailings

    def get_subscription_status(self, slug: str, user_id: int):
        """
        Получает статус подписки пользователя на рассылку
        """
        return self.query(
            f"SELECT {slug} FROM vk_subscriptions WHERE user_id={user_id}"
        )[0][0]

    def is_user_exist(self, user_id: int):
        """
        Возвращает информацию о том, существует ли пользователь в базе данных
        """
        user = self.query(f"SELECT id FROM users WHERE vk_id={user_id}")
        return bool(user)

    def is_session_exist(self, user_id: int):
        user = self.query(f"SELECT id FROM sessions WHERE vk_id={user_id}")
        return bool(user)

    def create_user(self, user_id: int):
        """
        Добавляет нового пользователя в таблицы информации и рассылок
        """
        self.query(f"INSERT INTO users (vk_id) VALUES ({user_id})")
        self.query(f"INSERT INTO vk_subscriptions DEFAULT VALUES")

    def create_session(self, user_id: int):
        """
        Создает новую сессию для пользователя
        """
        _id = self.query(f"SELECT id from users WHERE vk_id={user_id}")[0][0]
        self.query(
            f"INSERT INTO sessions (id, vk_id, state) VALUES ({_id}, {user_id}, main)"
        )
