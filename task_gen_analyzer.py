import re
import logging
import json
import tempfile
import subprocess
import os
logger = logging.getLogger(__name__)

SKILL_LIST = ["lists", "strings", "dicts", "sets", "functions", "algorithms", "list_comprehensions", "iterables"]

def generate_task_prompt(topic: str = None, difficulty: str = None) -> str:
    """
    Генерация промпта для создания задачи
    Аргументы:
        topic: тема задачи
        difficulty: сложность задачи
    Возвращает:
        Текст промпта для генерации задачи
    """
    return f"""
    Вы — эксперт по генерации задач по программированию на Python для технического интервью кандидатов. Сгенерируйте ОДНУ задачу в ТОЧНОМ формате, приведённом ниже.
    Строго соблюдайте структуру: Заголовок, Текст задачи, Сложность, Тема, Идеальное решение, Неправильное решение, Тесты.
    Используйте реалистичные, практические задачи. НЕ добавляйте никаких дополнительных полей или объяснений. Задачи должны быть не очень большими, чтобы не занимать слишком много времени кандидата.
    Все задачи должны решаться в максимум 10 +- 5 строк, не более. Большие задачи на код не использовать!
    Сделай тесты, которые можно запускать автоматически (автотесты), например через Докер. Не делай сложных вещей и не добавляй различные знаки по типу "/n". Все должно быть автоматизированно.

    Пример формата:
    ---
    title: Сумма списка
    task_text: Напишите функцию solve(nums), которая принимает список чисел и возвращает их сумму.
    difficulty: easy
    topic: lists
    ideal_solution: def solve(nums): return sum(nums)
    wrong_solution: def solve(nums): return len(nums)
    test_cases: [{{"input": [1,2,3], "output": 6}}, {{"input": [10, -5, 2], "output": 7}}]
    ---

    Сгенерируйте новую задачу по теме "{topic}", сложности "{difficulty}".
    Выводите ТОЛЬКО блок задачи между строками --- . Без лишнего текста!
    """

def extract_task_block(text: str):
    """
    Извлечение блока задачи из текста промпта
    Аргументы:
        text: текст, содержащий задачу из промпта
    Возвращает:
        Блок задачи или None
    """
    match = re.search(r'---\n(.*?)\n---', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    else:
        return None

def parse_task_block(block: str) -> dict:
    """
    Парсинг блока задачи в словарь
    Аргументы:
        block: текстовый блок задачи
    Возвращает:
        Словарь с данными задачи
    """
    lines = block.splitlines()
    task = {}
    current_key = None
    current_value = []

    for line in lines:
        if ':' in line and not line.startswith(' '):
            if current_key:
                task[current_key] = '\n'.join(current_value).strip()
            key, value = line.split(':', 1)
            current_key = key.strip()
            current_value = [value.strip()]
        else:
            current_value.append(line.strip())

    if current_key:
        task[current_key] = '\n'.join(current_value).strip()

    return task

def code_feedback_prompt(code: str, task_text: str) -> str:
    """
    Генерация промпта для анализа кода, который прислал пользователь
    Аргументы:
        code: код пользователя
        task_text: текст задачи
    Возвращает:
        Текст промпта для анализа
    """
    return f"""
    Ты — строгий технический эксперт по Python 
    Твоя задача — проверить, решает ли код ПОСТАВЛЕННУЮ задачу
    ВАЖНО: Поле "correct" должно быть "true" ТОЛЬКО ЕСЛИ код успешно проходит ВСЕ возможные тест-кейсы, включая граничные случаи, которые могут быть не указаны явно.
    Если код не реализует требуемый класс/функцию, или не содержит логики, соответствующей описанию — correct = false.
    Если код содержит только встроенную функцию (list, print, len и т.п.) без реализации задачи — correct = false.
    Если код синтаксически валиден, но не решает задачу — correct = false.
    Если код возвращает неправильный результат хотя бы для одного сценария — correct = false.
    Проанализируй решение кандидатом задачи на Python. Ответь строго в формате JSON. Оцени:
    1. correct — решает ли задачу? Варианты: true / false
    2. time_complexity — Big-O по времени (например: "O(n)", "O(n^2)")
    3. space_complexity — Big-O по памяти
    4. optimal — оптимально ли решение? (0–1)
    5. style — читаемость, имена, документация (0–1)
    6. PEP8 - проверка PEP8 (0–1)
    7. comment — краткий комментарий (1 предложение)
    8. detailed_feedback — подробный комментарий для отчета (включает как хорошие, так и плохие момент кода решения)
    9. ChatGPT_style - вероятность того, что код написал с помощью LLM (0–1)

    Задача: {task_text}
    Код: {code}
    Пример вывода - Ответ (только JSON, без пояснений):
    {{
    "correct": true,
    "time_complexity": "O(n)",
    "space_complexity": "O(1)",
    "optimal": 0.95,
    "PEP8": 1.0,
    "style": 0.8,
    "comment": "Идеальное решение: линейное время, минимум памяти.",
    "detailed_feedback": "Хороший момент: эффективное использование памяти. Не очень момент: можно использовать более понятные имена переменных.",
    "ChatGPT_style": 0.25
    }}

    Без лишнего текста.
    """

def check_pep8_with_flake8(code: str) -> float:
    """
    Проверка PEP8 с помощью flake8 (объединяет несколько линтеров)
    Линтеры — это программы, которые автоматически проверяют код на ошибки, несоответствия стилю и потенциальные проблем
    Pycodestyle - Проверяет стиль оформления кода на соответствие стандарту PEP8 (длина строки, названия переменных, и т.п.)
    Pyflakes - Ищет логические ошибки (неиспользуемые переменные, обращение к несуществующим переменным, и т.п.)
    McCabe complexity - Считает цикломатическую сложность функций (насколько сложно понять логику)
    Аргументы::
        code: код для проверки 
    Вовзвращает:
        Оценка PEP8 (0-1)
    """
    # Если код — мусор (не Python), возвращаем 0
    if not code.strip() or not code.replace(' ', '').replace('\n', '').replace('\t', ''):
        return 0.0
    
    try:
        # создать временный .py файл
        # вызвать команду flake8
        # Создаем временный файл с кодом
        # создаётся временный файл с расширением .py
        # записывается код
        # сохраняется путь к файлу
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            temp_file.write(code)
            temp_file_path = temp_file.name
        # Запускаем flake8
        result = subprocess.run(['flake8', temp_file_path, '--max-line-length=88'], 
                               capture_output=True, text=True)
        # Удаляем временный файл
        os.unlink(temp_file_path)
        # Если есть ошибки, возвращаем оценку
        if result.returncode == 0:
            return 1.0  # Нет ошибок PEP8
        else:
            # Считаем количество ошибок
            errors = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
            # Оценка уменьшается с увеличением ошибок
            # 1 ошибка → 0.9
            # 2 ошибки → 0.8
            # 10+ ошибок → 0.0
            # оценка никогда не уйдёт ниже 0.0
            return max(0.0, 1.0 - (errors * 0.1))
    
    except Exception as e:
        logger.warning(f"Ошибка при проверке PEP8: {e}")
        return 0.0  # Возвращаем среднюю оценку при ошибке
    
def analyze_code_with_llm_and_pep8(code: str, task_text: str, llm) -> dict:
    """
    Анализ кода с помощью LLM QWEN и проверка PEP8
    Аргументы:
        code: код пользователя
        task_text: текст задачи
        ### test_cases: список тест-кейсов из БД (с ключами 'call' и 'output')
        llm: экземпляр LLM модели
    Возвращает:
        Словарь с результатами анализа
    """
    # Проверим, является ли код валидным Python-выражением/функцией
    try:
        compile(code, '<string>', 'exec')  # ← проверяет синтаксис
    except SyntaxError:
        # Если ошибка — сразу возвращаем неправильное решение
        return {
            "correct": False,
            "time_complexity": "N/A",
            "space_complexity": "N/A",
            "optimal": 0.0,
            "PEP8": 0.0,
            "style": 0.0,
            "comment": "Синтаксическая ошибка в коде",
            "detailed_feedback": "Код содержит синтаксические ошибки и не может быть выполнен.",
            "ChatGPT_style": 0.0
        }
    
    # Если синтаксис корректен — анализируем через LLM
    pep8_score = check_pep8_with_flake8(code)
    # Генерируем промпт для LLM
    prompt = code_feedback_prompt(code, task_text)
    # Отправляем промпт в модель
    try:
        response = llm.chat.completions.create(
            model="qwen3-coder-30b-a3b-instruct-fp8",   # указываем модель SciBox
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            top_p=0.9,
            max_tokens=1000,
            )
        generated_text = response.choices[0].message.content.strip()
        
        # Безопасный парсинг JSON
        try:
            # Ищем начало и конец JSON
            start = generated_text.find('{')
            end = generated_text.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = generated_text[start:end]
                parsed_obj = json.loads(json_str)
                # Проверяем, что parsed_obj - это словарь
                if isinstance(parsed_obj, dict):
                    feedback = parsed_obj
                else:
                    logger.error("Ответ LLM не является JSON-объектом (не словарь)")
                    feedback = {
                        "correct": False,
                        "time_complexity": "unknown",
                        "space_complexity": "unknown",
                        "optimal": 0.0,
                        "PEP8": pep8_score,
                        "style": 0.0,
                        "comment": "Ошибка при анализе кода",
                        "detailed_feedback": "Произошла ошибка при анализе кода. Ответ LLM не в ожидаемом формате (не словарь).",
                        "ChatGPT_style": 0.0
                    }
            else:
                raise json.JSONDecodeError("No JSON found", generated_text, 0)
        except json.JSONDecodeError:
            logger.error("Не удалось распарсить JSON из ответа LLM")
            feedback = {
                "correct": False,
                "time_complexity": "unknown",
                "space_complexity": "unknown",
                "optimal": 0.0,
                "PEP8": pep8_score,
                "style": 0.0,
                "comment": "Ошибка при анализе кода",
                "detailed_feedback": "Произошла ошибка при анализе кода. Пожалуйста, проверьте синтаксис.",
                "ChatGPT_style": 0.0
            }
        
        # Объединяем результат выполнения тестов с результатом LLM
        llm_correct_result = feedback.get('correct', False)
        #final_correct = test_passed and llm_correct_result
        final_correct = llm_correct_result
        
        # Обновляем итоговый feedback с финальным значением correct
        feedback['correct'] = final_correct
        
        # Обновляем PEP8 оценку, если LLM дал свою
        if 'PEP8' in feedback:
            # Среднее между LLM и flake8
            feedback['PEP8'] = (feedback['PEP8'] + pep8_score) / 2
        else:
            feedback['PEP8'] = pep8_score
            
    except Exception as e:
        logger.error(f"Ошибка при анализе кода: {e}")
        feedback = {
            "correct": False,
            "time_complexity": "unknown",
            "space_complexity": "unknown",
            "optimal": 0.0,
            "PEP8": pep8_score,
            "style": 0.0,
            "comment": "Ошибка при анализе кода",
            "detailed_feedback": "Произошла ошибка при анализе кода.",
            "ChatGPT_style": 0.0
        }
    
    return feedback

def generate_task_with_llm(topic: str, difficulty: str, llm):
    """
    Генерация задачи с помощью LLM
    Аргументы:
        topic: тема задачи
        difficulty: сложность
        llm: экземпляр LLM модели
    Возвращает:
        Словарь с задачей или None
    """
    prompt = generate_task_prompt(topic, difficulty)
    
    try: 
        response = llm.chat.completions.create(
            model="qwen3-coder-30b-a3b-instruct-fp8",   # указываем модель SciBox
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            top_p=0.9,
            max_tokens=1000,
            )

        generated_text = response.choices[0].message.content.strip()
        
        # Извлекаем блок задачи
        task_block = extract_task_block(generated_text)
        
        if not task_block:
            logger.error("Не удалось извлечь блок задачи")
            return None
        
        # Парсим задачу
        parsed_task = parse_task_block(task_block)
        
        return parsed_task
        
    except Exception as e:
        logger.error(f"Ошибка при генерации задачи: {e}")
        return None
    
def generate_hint_prompt(task_text: str, user_code: str) -> str:
    """
    Генерация промпта для получения подсказки от LLM
    """
    return f"""
    Ты — помощник по программированию. Кандидат на вакансию решает задачу:

    Задача:
    {task_text}

    Его код:
    {user_code}

    Дай краткую подсказку, как улучшить или исправить код.
    Не решай задачу за него. Не давай полный код.
    Подсказка должна быть полезной, но не очевидной.
    Ответь в формате JSON:
    {{
        "hint": "Твоя подсказка"
    }}
    """

def get_hint_from_llm(task_text: str, user_code: str, llm) -> str:
    """
    Получение подсказки от LLM
    """
    prompt = generate_hint_prompt(task_text, user_code)
    
    try:
        response = llm.chat.completions.create(
            model="qwen3-coder-30b-a3b-instruct-fp8",   # указываем модель SciBox
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            top_p=0.9,
            max_tokens=256,
            )
        generated_text = response.choices[0].message.content.strip()
        # Попробуем распарсить JSON
        try:
            # Ищем JSON в тексте
            start = generated_text.find('{')
            end = generated_text.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = generated_text[start:end]
                hint_data = json.loads(json_str)
                return hint_data.get("hint", "Нет подсказки")
            else:
                # Если нет JSON — возвращаем как есть
                return generated_text
        except json.JSONDecodeError:
            return generated_text
        
    except Exception as e:
        logger.error(f"Ошибка при генерации подсказки: {e}")
        return "Сейчас подсказка недоступна. Попробуйте позже."