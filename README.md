# RALPH
## Бот – платформа, призванный управлять студеческой беседой и упростить работу старост.
![Code style](https://img.shields.io/static/v1?label=Code%20style&message=PEP8&color=informational)
![Pyup](https://pyup.io/repos/github/dadyarri/ralph/shield.svg)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Scrutinizer Code Quality](https://scrutinizer-ci.com/g/dadyarri/ralph/badges/quality-score.png?b=master)](https://scrutinizer-ci.com/g/dadyarri/ralph/?branch=master)
[![Build Status](https://travis-ci.org/dadyarri/ralph.svg?branch=master)](https://travis-ci.org/dadyarri/ralph)
### О проекте
RALPH - это платформа, созданная для того, чтобы упросить нелёгкий труд старост в студенческих групах.

Он работает как бот ВКонтакте, которого можно добавить в беседу, где он и будет выполнять свои функции.
### Описание функционала
Бот управляется с помощью встроенной клавиатуры ВКонтакте. Для ее вызова в первый раз необходимо отправить сообщение с текстом "Начать" (или нажать соответствующую кнопку)
1. Общий призыв (отправка в беседу сообщения с упоминаниями всех студентов)
2. Призыв с сообщением (отправка в беседу сообщения с упоминанием всех студентов, плюс указанное объявление)
3. Призыв должников (отправка в беседу сообщения с упоминанием студентов, не сдавших деньги на указанную цель)
4. Получение расписания на сегодня
5. Получение расписания на завтра

**Функции 1-3 требуют доступа администратора**