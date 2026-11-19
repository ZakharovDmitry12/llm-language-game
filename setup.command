#!/bin/bash
# Установка зависимостей для анализа в отдельное окружение проекта.
set -e
cd "$(dirname "$0")"
trap 'echo; echo "Установка завершилась с ошибкой. Посмотрите сообщение выше."; read -r -p "Нажмите Enter для закрытия..."' ERR
if ! command -v python3 >/dev/null 2>&1; then
  echo "Не найден python3. Установите Python 3 и повторите запуск."
  exit 1
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-analysis.txt
echo
echo "Окружение создано в .venv. Дальнейшие команды — в README.md."
read -r -p "Нажмите Enter для закрытия..."
