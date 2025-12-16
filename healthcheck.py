#!/usr/bin/env python3
"""
Health check скрипт для Docker контейнера.
Проверяет доступность файла состояния и работоспособность бота.
"""

import os
import sys
import json
import time

def check_health():
    """Проверяет здоровье приложения."""
    state_file = os.environ.get("STATE_FILE", "state/last.json")
    
    # Проверяем существование файла состояния (означает, что бот работал)
    if not os.path.exists(state_file):
        # Если файла нет, это может быть первый запуск - это нормально
        # Проверяем, что директория существует и доступна для записи
        state_dir = os.path.dirname(state_file)
        if state_dir and not os.path.exists(state_dir):
            try:
                os.makedirs(state_dir, exist_ok=True)
            except Exception:
                return False
        
        # Проверяем возможность записи
        try:
            test_file = state_file + ".healthcheck"
            with open(test_file, "w") as f:
                json.dump({"healthcheck": time.time()}, f)
            os.remove(test_file)
        except Exception:
            return False
    
    # Проверяем, что файл состояния валидный JSON
    try:
        if os.path.exists(state_file):
            with open(state_file, "r", encoding="utf-8") as f:
                json.load(f)
    except (json.JSONDecodeError, IOError):
        # Поврежденный файл - это проблема, но не критичная
        pass
    
    return True

if __name__ == "__main__":
    if check_health():
        sys.exit(0)
    else:
        sys.exit(1)

