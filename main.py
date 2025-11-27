from openai import OpenAI
from db import create_all_tables, get_task_from_db, save_user_attempt, get_user_bkt_state, update_user_bkt_state, format_task_for_db, insert_task_to_db
from task_gen_analyzer import generate_task_with_llm, analyze_code_with_llm_and_pep8, get_hint_from_llm, SKILL_LIST
from report import generate_user_report
from bkt_recommend import BKT
from datetime import datetime
import os
import random

# LLM
API_KEY = os.getenv("SCIBOX_API_KEY") 
if not API_KEY:
    raise ValueError("SCIBOX_API_KEY не найден в .env")
BASE_URL = "https://llm.t1v.scibox.tech/v1" 
llm_coder = OpenAI(api_key=API_KEY, base_url=BASE_URL)
llm_report = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# Константы
CRITICAL_SKILL_THRESHOLD = 0.2 # не топить кандидата по одной и той же теме
HIGH_SKILL_THRESHOLD = 0.9 # не захваливать кандидата по одной и той же теме
MAX_HINTS_PER_TASK = 2 # максимальное число подсказок на задачу

def load_or_init_bkt(user_id: str) -> BKT:
    """Загружает состояние BKT из БД или создаёт новую модель."""
    loaded_bkt = get_user_bkt_state(user_id)
    if loaded_bkt is not None:
        print(f"BKT загружена из БД: {loaded_bkt.state}")
        return loaded_bkt
    else:
        bkt_model = BKT()
        print(f"Создана новая BKT: {bkt_model.state}")
        return bkt_model

def select_skill_for_task(bkt_model: BKT, available_skills: set) -> str:
    """
    Выбирает навык для следующей задачи:
    - Если рекомендованный навык критически низкий  ищем альтернативу
    - Если рекомендованный навык высокий - ищем альтернативу
    - Иначе — используем рекомендованный
    - учитываем рекомендованный диапазон сложности (max_diff)
    """
    recommended_skill = bkt_model.get_recommendation_skill()
    current_level = bkt_model.state.get(recommended_skill, bkt_model.pL0) if recommended_skill else bkt_model.pL0

    # Логика для КРИТИЧЕСКИ НИЗКОГО навыка
    if recommended_skill and current_level < CRITICAL_SKILL_THRESHOLD:
        print(f"Навык '{recommended_skill}' критически низок ({current_level:.2f}). Пытаемся найти другую тему.")
        available_skills.discard(recommended_skill)
        available_skills = {skill for skill in available_skills if bkt_model.state.get(skill, bkt_model.pL0) <= HIGH_SKILL_THRESHOLD}

        if available_skills:
            # max_diff для каждого доступного навыка
            potential_skills = {}
            for skill in available_skills:
                min_diff, max_diff = bkt_model.get_recommended_difficulty_range(skill)
                potential_skills[skill] = {
                    'level': bkt_model.state.get(skill, bkt_model.pL0),
                    'max_diff': max_diff,
                    'is_critical': bkt_model.state.get(skill, bkt_model.pL0) < CRITICAL_SKILL_THRESHOLD
                }
            # Фильтруем критические навыки
            non_critical_potential = {sk: data for sk, data in potential_skills.items() if not data['is_critical']}
            
            if non_critical_potential:
                # навык с минимальным level (но не критическим)
                selected_skill = min(non_critical_potential, key=lambda x: non_critical_potential[x]['level'])
                print(f"Выбрана альтернативная тема: '{selected_skill}' (уровень: {non_critical_potential[selected_skill]['level']:.2f}, max_diff: {non_critical_potential[selected_skill]['max_diff']:.2f})")
            elif potential_skills:
                # Все доступные навыки критические — выбираем с максимальным max_diff (чтобы не застревать)
                selected_skill = max(potential_skills, key=lambda x: potential_skills[x]['max_diff'])
                print(f"Все доступные темы критические. Выбрана наименее критическая: '{selected_skill}' (уровень: {potential_skills[selected_skill]['level']:.2f}, max_diff: {potential_skills[selected_skill]['max_diff']:.2f})")
            else:
                selected_skill = recommended_skill
                print(f"Нет доступных альтернативных тем. Продолжаем с критическим навыком '{recommended_skill}'.")
        else:
            selected_skill = recommended_skill
            print(f"Нет доступных альтернативных тем. Продолжаем с критическим навыком '{recommended_skill}'.")
        return selected_skill

    # Логика для ВЫСОКОГО навыка
    elif recommended_skill and current_level >= HIGH_SKILL_THRESHOLD:
        print(f"Рекомендованный навык '{recommended_skill}' хорошо освоен ({current_level:.2f}). Пытаемся найти другую тему.")
        available_skills.discard(recommended_skill)
        available_skills = {skill for skill in available_skills if bkt_model.state.get(skill, bkt_model.pL0) < HIGH_SKILL_THRESHOLD}

        if available_skills:
            # max_diff для каждого доступного навыка
            potential_skills = {}
            for skill in available_skills:
                min_diff, max_diff = bkt_model.get_recommended_difficulty_range(skill)
                potential_skills[skill] = {
                    'level': bkt_model.state.get(skill, bkt_model.pL0),
                    'max_diff': max_diff,
                    'is_critical': bkt_model.state.get(skill, bkt_model.pL0) < CRITICAL_SKILL_THRESHOLD
                }

            # навык с минимальным level (ниже HIGH_SKILL_THRESHOLD)
            selected_skill = min(potential_skills, key=lambda x: potential_skills[x]['level'])
            print(f"Выбрана альтернативная тема (ниже {HIGH_SKILL_THRESHOLD}): '{selected_skill}' (уровень: {potential_skills[selected_skill]['level']:.2f}, max_diff: {potential_skills[selected_skill]['max_diff']:.2f})")
        else:
            selected_skill = random.choice(SKILL_LIST)
            print(f"Все навыки хорошо освоены. Выбрана случайная тема: '{selected_skill}'.")
        return selected_skill

    # Общий случай
    else:
        if recommended_skill:
            # Добавляем max_diff в вывод
            min_diff, max_diff = bkt_model.get_recommended_difficulty_range(recommended_skill)
            print(f"Рекомендована тема: '{recommended_skill}' (уровень: {current_level:.2f}, max_diff: {max_diff:.2f})")
            return recommended_skill
        else:
            selected_skill = random.choice(SKILL_LIST)
            print(f"Нет известных навыков. Выбрана случайная тема: '{selected_skill}'.")
            return selected_skill

def determine_difficulty(skill_level: float, bkt_model: BKT, skill: str) -> str:
    """
    Определяет сложность задачи на основе рекомендованного диапазона от BKT
    Возвращает: 'easy', 'medium' или 'hard'
    """
    min_diff, max_diff = bkt_model.get_recommended_difficulty_range(skill)

    if min_diff <= 0.33:
        return "easy"
    elif min_diff <= 0.66:
        return "medium"
    else:
        return "hard"
    
def generate_new_task(skill: str, llm, bkt_model: BKT) -> dict | None:
    """Генерирует новую задачу для указанного навыка."""
    difficulty = determine_difficulty(bkt_model.state.get(skill, bkt_model.pL0), bkt_model, skill)
    min_diff, max_diff = bkt_model.get_recommended_difficulty_range(skill)
    print(f"Уровень навыка '{skill}': {bkt_model.state.get(skill, bkt_model.pL0):.2f}")
    print(f"Рекомендованный диапазон сложности: [{min_diff:.2f}, {max_diff:.2f}]")
    print(f"Выбрана сложность: {difficulty}")
    raw_task = generate_task_with_llm(skill, difficulty, llm)
    if not raw_task:
        print("Не удалось сгенерировать задачу.")
        return None

    task_for_db = format_task_for_db(raw_task)
    task_id = insert_task_to_db(task_for_db)
    task_for_db['id'] = task_id
    print(f"Новая задача сгенерирована и добавлена в БД: {task_for_db['title']}")
    return task_for_db

def get_or_generate_task(user_id: str, bkt_model: BKT, skill_to_focus: str, llm, used_task_ids: set) -> dict | None:
    """
    Получает задачу из БД или генерирует новую.
    При необходимости генерирует новую задачу, если текущая уже была использована.
    """
    task = get_task_from_db(user_id, bkt_model, skill_to_focus_override=skill_to_focus)
    if not task:
        print(f"Нет подходящих задач в БД для навыка '{skill_to_focus}'. Генерируем новую...")
        task = generate_new_task(skill_to_focus, llm, bkt_model)
        if not task:
            return None

    # не была ли задача уже в этом сеансе (не повторяем задачи)
    while task and task['id'] in used_task_ids:
        print(f"Задача {task['id']} уже была. Генерируем новую...")
        task = generate_new_task(skill_to_focus, llm, bkt_model)
        if not task:
            break

    if not task:
        print("Не удалось получить или сгенерировать задачу. Пропуск итерации.")
        return None

    used_task_ids.add(task['id'])
    print(f"Задача: {task['title']}")
    print(f"Текст: {task['text']}")
    return task

def collect_hints(task_text: str, llm, max_hints: int = MAX_HINTS_PER_TASK) -> list:
    """Собирает подсказки от пользователя.
    Максимальное число подсказок ограничили в MAX_HINTS_PER_TASK = 2"""
    hints_used = []
    for _ in range(max_hints):
        use_hint = input(f"Нужна подсказка? ({max_hints - len(hints_used)} осталось) (y/n): ").strip().lower()
        if use_hint != 'y':
            break
        user_code_stub = input("Введите ваш текущий код (или вопрос по заданию): ")
        hint = get_hint_from_llm(task_text, user_code_stub, llm)
        print(f"Подсказка: {hint}")
        hints_used.append({"text": hint, "timestamp": str(datetime.now())})
    return hints_used

def run_single_cycle(user_id: str, bkt_model: BKT, llm, used_task_ids: set) -> bool:
    """
    Выполняет один цикл: получение задачи → решение → анализ → обновление BKT.
    Возвращает True, если цикл успешно завершён.
    """
    # Определяем навык для задачи
    available_skills = set(SKILL_LIST)
    skill_to_focus = select_skill_for_task(bkt_model, available_skills)

    # Получаем или генерируем задачу
    task = get_or_generate_task(user_id, bkt_model, skill_to_focus, llm, used_task_ids)
    if not task:
        return False

    # Решение задачи
    started_at = datetime.now() # старт решения
    hints_used = collect_hints(task['text'], llm)
    user_code = input("Введите код: ")
    finished_at = datetime.now() # окончание решения

    print(f"Код пользователя:\n{user_code}")

    # Анализ кода
    feedback = analyze_code_with_llm_and_pep8(user_code, task['text'], llm_coder)
    print(f"Анализ кода: {feedback}")

    # Обновляем BKT
    skill = task['topic']
    skill_level_before = bkt_model.state.get(skill, bkt_model.pL0)
    correct = feedback.get('correct', False)
    skill_level_after = bkt_model.update(skill, correct)
    print(f"Навык '{skill}' обновлен: {skill_level_before:.2f} → {skill_level_after:.2f}")

    # Сохраняем попытку в БД
    save_user_attempt(
        user_id=user_id,
        task_id=task['id'],
        code=user_code,
        feedback=feedback,
        skill_level_before=skill_level_before,
        skill_level_after=skill_level_after,
        started_at=str(started_at),
        finished_at=str(finished_at),
        hints_used=hints_used
    )
    print("Попытка сохранена в БД.")

    # Обновляем BKT в БД
    update_user_bkt_state(user_id, bkt_model)
    print("Состояние BKT обновлено в БД.")

    return True

def run_full_cycle(user_id: str, llm, cycles: int):
    """Запуск цикла задача → анализ → обновление BKT → следующая задача"""
    print(f"Запуск цикла для пользователя {user_id}, {cycles} итераций")

    # Создаём таблицы, если не существуют
    create_all_tables()

    # Загружаем состояние bkt из БД
    bkt_model = load_or_init_bkt(user_id)

    # Храним ID задач, которые уже были в этом сеансе -> чтобы не повторяться
    used_task_ids = set()

    for i in range(cycles):
        print(f"\n--- Цикл {i+1}/{cycles} ---")
        rounded_skills = {k: round(v, 2) for k, v in bkt_model.state.items()}
        print(f"Текущие навыки: {rounded_skills}")

        success = run_single_cycle(user_id, bkt_model, llm, used_task_ids)
        if not success:
            print("Цикл пропущен из-за ошибки получения/генерации задачи.")

    # Генерируем отчет
    print("\n--- Генерация отчета ---")
    report = generate_user_report(user_id, llm_client=llm_report)
    print("\nПерсонализированный фидбек:")
    print(report.get("human_feedback", ""))


if __name__ == "__main__":
    run_full_cycle('1', llm_coder, cycles=6)