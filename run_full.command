#!/bin/bash
set -u
cd "$(dirname "$0")" || exit 1

db=data/main_luna_qwen_hy4.sqlite
python=.venv/bin/python
if [[ ! -x "$python" ]]; then
  echo "Сначала запустите setup.command в этой папке."
  exit 1
fi

if [[ -f "$db" ]]; then
  echo "Продолжение серии из $db. Лимит включает уже записанный расход."
else
  echo "Полная серия на Luna, Qwen и Hy4. До 11 100 запросов OpenRouter."
fi
read -r -p 'Суммарный лимит этой серии в USD (например, 0.40): ' budget || exit 1
read -r -s -p 'API-ключ OpenRouter: ' OPENROUTER_API_KEY || exit 1
echo
export OPENROUTER_API_KEY

if [[ ! -f "$db" ]]; then
  "$python" -m lg_game generate --db "$db" --preset full --seed 20261119 || exit "$?"
fi

/usr/bin/caffeinate -i "$python" -m lg_game run --db "$db" --budget "$budget"
status=$?
unset OPENROUTER_API_KEY
if [[ "$status" -ne 0 ]]; then
  echo "Серия остановилась. После устранения причины запустите этот файл снова."
  read -r -p 'Нажмите Enter для закрытия…' _
  exit "$status"
fi

"$python" -m lg_game export --db "$db" --out data/main_luna_qwen_hy4.csv || exit "$?"
"$python" analysis.py data/main_luna_qwen_hy4.csv --output results/main_luna_qwen_hy4 || exit "$?"
echo "Готово. Таблицы и графики находятся в results/main_luna_qwen_hy4."
read -r -p 'Нажмите Enter для закрытия…' _
