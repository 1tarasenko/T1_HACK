import psycopg2
import json
import logging
from bkt_recommend import BKT
import os
from dotenv import load_dotenv
from task_gen_analyzer import SKILL_LIST
import random

load_dotenv()
DB_CONFIG = {
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT', 5432)), 
    'database': os.getenv('DB_NAME')
}
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_connection():
    """Создание подключения к PostgreSQL"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к PostgreSQL: {e}")
        raise
    
def create_all_tables():
    """Создание всех необходимых таблиц"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Создание таблицы Users
    create_users_table = """
    CREATE TABLE IF NOT EXISTS Users (
        id_user SERIAL PRIMARY KEY,
        user_id TEXT UNIQUE NOT NULL,
        name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    # Создание таблицы Tasks
    create_tasks_table = """
    CREATE TABLE IF NOT EXISTS Tasks (
        id_task SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        topic TEXT NOT NULL,
        ideal_solution TEXT NOT NULL,
        wrong_solution TEXT NOT NULL,
        test_cases JSONB NOT NULL
    );
    """
    # Создание таблицы UserProgress
    create_user_progress_table = """
    CREATE TABLE IF NOT EXISTS UserProgress (
        id SERIAL PRIMARY KEY,
        id_user INTEGER NOT NULL REFERENCES Users(id_user),
        id_task INTEGER NOT NULL REFERENCES Tasks(id_task),
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT NOT NULL,
        comments TEXT,
        feedback JSONB NOT NULL,
        skill_level_before FLOAT NOT NULL,
        skill_level_after FLOAT NOT NULL,
        code TEXT NOT NULL,
        hints_used JSONB
    );
    """
    # Создание таблицы UserSkills
    create_user_skills_table = """
    CREATE TABLE IF NOT EXISTS UserSkills (
        id SERIAL PRIMARY KEY,
        id_user INTEGER NOT NULL REFERENCES Users(id_user),
        skill_name TEXT NOT NULL,
        skill_level FLOAT NOT NULL DEFAULT 0.5,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(id_user, skill_name)
    );
    """
    # Создание таблицы UserFeedback
    create_user_feedback_table = """
    CREATE TABLE IF NOT EXISTS UserFeedback (
        id SERIAL PRIMARY KEY,
        id_user_progress INTEGER NOT NULL REFERENCES UserProgress(id),
        correct BOOLEAN NOT NULL,
        time_complexity TEXT,
        space_complexity TEXT,
        chatgpt_style FLOAT,
        optimal FLOAT,
        style FLOAT,
        pep8 FLOAT,
        comment TEXT,
        detailed_feedback TEXT,
        hints_used_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """
    cursor.execute(create_users_table)
    cursor.execute(create_tasks_table)
    cursor.execute(create_user_progress_table)
    cursor.execute(create_user_skills_table)
    cursor.execute(create_user_feedback_table)
    conn.commit()
    cursor.close()
    conn.close()
    logger.info("Все таблицы созданы")
    
def get_user_id_by_external_id(user_id: str) -> int:
    """Получение внутреннего id_user по внешнему user_id"""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
    INSERT INTO Users (user_id) VALUES (%s) 
    ON CONFLICT (user_id) DO UPDATE SET user_id = EXCLUDED.user_id
    RETURNING id_user;
    """
    cursor.execute(query, (user_id,))
    result = cursor.fetchone()
    
    conn.commit()
    cursor.close()
    conn.close()
    
    if result:
        return result[0]
    else:
        raise Exception(f"Не удалось получить id_user для user_id={user_id}")
    
def get_user_bkt_state(user_id: str):
    """Получение текущего состояния BKT из UserSkills"""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Получаем внутренний id_user
    id_user = get_user_id_by_external_id(user_id)
    query = "SELECT skill_name, skill_level FROM UserSkills WHERE id_user = %s;"
    cursor.execute(query, (id_user,))
    skills_data = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    bkt = BKT()
    for skill_name, skill_level in skills_data:
        bkt.state[skill_name] = skill_level
    
    return bkt

def update_user_bkt_state(user_id: str, bkt_model):
    """Обновление состояния BKT в UserSkills"""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Получаем внутренний id_user
    id_user = get_user_id_by_external_id(user_id)
    for skill_name, skill_level in bkt_model.state.items():
        # Округляем уровень до 2 знаков
        skill_level = round(skill_level, 2)
        query = """
        INSERT INTO UserSkills (id_user, skill_name, skill_level) 
        VALUES (%s, %s, %s) 
        ON CONFLICT (id_user, skill_name) 
        DO UPDATE SET skill_level = EXCLUDED.skill_level, last_updated = CURRENT_TIMESTAMP;
        """
        cursor.execute(query, (id_user, skill_name, skill_level))
    
    conn.commit()
    cursor.close()
    conn.close()

def get_task_from_db(user_id: str, bkt_model, skill_to_focus_override: str = None):
    """Получение задачи из Tasks на основе BKT
    - Берёт рекомендованный навык из BKT-модели
    - Определяет уровень сложности задач, подходящий под текущий уровень
    - Делает запрос в PostgreSQL
    - выбирает случайную задачу подходящей сложности
    - по нужному навыку (topic = skill_to_focus)
    - Если таких задач нет → берёт любую случайную задачу"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем навык для фокуса:
    skill_to_focus = skill_to_focus_override or bkt_model.get_recommendation_skill()
    if skill_to_focus is None or skill_to_focus not in SKILL_LIST:
        skill_to_focus = random.choice(SKILL_LIST)
        print(f"get_task_from_db: Не удалось определить навык, выбран случайный: {skill_to_focus}")
    
    # Получаем список ВСЕХ задач, которые пользователь уже решал
    all_tasks_query = """
    SELECT up.id_task FROM UserProgress up
    JOIN Users u ON up.id_user = u.id_user
    WHERE u.user_id = %s;
    """
    
    cursor.execute(all_tasks_query, (user_id,))
    all_task_ids = [row[0] for row in cursor.fetchall()]
    
    # условие исключения (чтобы пользователю не падали одни и те же задачи)
    exclude_condition = ""
    # параметры для подстановки в SQL-запрос
    exclude_params = [skill_to_focus]
    
    # если есть задачи, которые нужно исключить
    if all_task_ids:
        # создаем плейсхолдеры для SQL: %s, %s, %s... в зависимости от количества задач
        placeholders = ','.join(['%s'] * len(all_task_ids))
        # добавляем условие исключения: задача НЕ в списке recent_task_ids
        exclude_condition = f" AND id_task NOT IN ({placeholders})"
        # добавляем ID задач в параметры запроса
        exclude_params.extend(all_task_ids)
    
    # Получаем рекомендуемый диапазон сложности для выбранного навыка
    min_diff, max_diff = bkt_model.get_recommended_difficulty_range(skill_to_focus)
    current_level = bkt_model.state.get(skill_to_focus, bkt_model.pL0)
    # # Преобразуем в уровни сложности
    # difficulty_levels = []
    # if min_diff <= 0.33:
    #     difficulty_levels.append('easy')
    # if 0.33 < min_diff <= 0.66 or 0.33 < max_diff <= 0.66:
    #     difficulty_levels.append('medium')
    # if max_diff > 0.66:
    #     difficulty_levels.append('hard')
    # if not difficulty_levels:
    #     difficulty_levels = ['easy']
    if current_level < 0.4:
        difficulty_levels = ['easy']
    elif current_level < 0.6:
        difficulty_levels = ['easy', 'medium']
    elif current_level < 0.8:
        difficulty_levels = ['medium', 'hard']
    else: 
        difficulty_levels = ['hard']
        
    if not difficulty_levels:
        difficulty_levels = ['easy']
    
    # Собираем строку для запроса
    # пример difficulty = 'easy' OR difficulty = 'medium'
    difficulty_condition = " OR ".join([f"difficulty = '{level}'" for level in difficulty_levels])
    
    # Основной запрос
    query = f"""
    SELECT id_task, title, text, difficulty, topic, ideal_solution, wrong_solution, test_cases
    FROM Tasks
    WHERE topic = %s AND ({difficulty_condition}) {exclude_condition}
    ORDER BY RANDOM()
    LIMIT 1;
    """

    cursor.execute(query, exclude_params)
    result = cursor.fetchone()
    
    if result:
        # Безопасный парсинг test_cases 
        try:
            test_cases = json.loads(result[7]) if isinstance(result[7], str) else result[7] if result[7] else []
        except (json.JSONDecodeError, TypeError):
            test_cases = result[7] if result[7] else []
        
        task = {
            'id': result[0],
            'title': result[1],
            'text': result[2],
            'difficulty': result[3],
            'topic': result[4],
            'ideal_solution': result[5],
            'wrong_solution': result[6],
            'test_cases': test_cases
        }
        
    else:
        # Fallback: без исключения задач (если нет подходящих)
        fallback_query = f"""
        SELECT id_task, title, text, difficulty, topic, ideal_solution, wrong_solution, test_cases
        FROM Tasks
        WHERE topic = %s AND ({difficulty_condition})
        ORDER BY RANDOM()
        LIMIT 1;
        """
        cursor.execute(fallback_query, (skill_to_focus,))
        fallback_result = cursor.fetchone()
        
        if fallback_result:
            # Безопасный парсинг test_cases
            try:
                test_cases = json.loads(fallback_result[7]) if isinstance(fallback_result[7], str) else fallback_result[7] if fallback_result[7] else []
            except (json.JSONDecodeError, TypeError):
                test_cases = fallback_result[7] if fallback_result[7] else []
            
            task = {
                'id': fallback_result[0],
                'title': fallback_result[1],
                'text': fallback_result[2],
                'difficulty': fallback_result[3],
                'topic': fallback_result[4],
                'ideal_solution': fallback_result[5],
                'wrong_solution': fallback_result[6],
                'test_cases': test_cases
            }
        else:
            task = None
            
    cursor.close()
    conn.close()
    return task

def save_user_attempt(user_id: str, task_id: int, code: str, feedback: dict, 
                     skill_level_before: float, skill_level_after: float, 
                     started_at: str, finished_at: str, hints_used: list = None):
    """Сохранение попытки пользователя решить задачу в таблицу UserProgress
    - пользователь
    - задача
    - время начала / окончания
    - статус
    - комментарий
    - отзыв
    - уровень навыка до / после
    - код
    - hints_used: список подсказок"""
    if hints_used is None:
        hints_used = []
    
    # Округляем уровни навыков до 2 знаков
    skill_level_before = round(skill_level_before, 2)
    skill_level_after = round(skill_level_after, 2)
    # Определяем статус
    correct = feedback.get('correct', False)
    status = 'success' if correct else 'failed'
    conn = get_db_connection()
    cursor = conn.cursor()
    # Получаем внутренний id_user
    id_user = get_user_id_by_external_id(user_id)
    # Изменяем основной INSERT, чтобы получить id новой записи UserProgress
    main_query = """
    INSERT INTO UserProgress (id_user, id_task, started_at, finished_at, status,  
                            comments, feedback, skill_level_before, skill_level_after, code, hints_used)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id; -- Запрашиваем id новой записи
    """
    
    # Генерируем комментарий из feedback
    # Если в feedback есть поле "comment" -> берём его
    # нет - пустая строка
    comment = feedback.get('comment', '') if isinstance(feedback, dict) else ''
    
    cursor.execute(main_query, (
        id_user, task_id, started_at, finished_at, status, comment, 
        json.dumps(feedback), skill_level_before, skill_level_after, 
        code, json.dumps(hints_used)
    ))
    
    # Получаем id только что вставленной записи в UserProgress
    user_progress_id = cursor.fetchone()[0]
    
    # Подготовка данных для вставки в UserFeedback
    # Извлекаем поля из словаря feedback, используя .get() для безопасности
    fb_correct = feedback.get('correct', False)
    fb_time_complexity = feedback.get('time_complexity')
    fb_space_complexity = feedback.get('space_complexity')
    fb_chatgpt_style = feedback.get('ChatGPT_style')
    fb_optimal = feedback.get('optimal')
    fb_style = feedback.get('style')
    fb_pep8 = feedback.get('PEP8') 
    fb_comment = feedback.get('comment')
    fb_detailed_feedback = feedback.get('detailed_feedback')
    hints_count = len(hints_used)
    
    # Вставка в UserFeedback
    feedback_query = """
    INSERT INTO UserFeedback (
        id_user_progress, correct, time_complexity, space_complexity, chatgpt_style,
        optimal, style, pep8, comment, detailed_feedback, hints_used_count
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """
    cursor.execute(feedback_query, (
        user_progress_id, fb_correct, fb_time_complexity, fb_space_complexity, fb_chatgpt_style,
        fb_optimal, fb_style, fb_pep8, fb_comment, fb_detailed_feedback, hints_count
    ))
    conn.commit()
    cursor.close()
    conn.close()
    logger.info(f"Попытка пользователя {user_id} по задаче {task_id} сохранена")
    
def format_task_for_db(raw_task: dict):
    """
    Преобразование задачи из формата LLM в формат, совместимый с БД
    """
    if not raw_task:
        return None
    topic = raw_task.get('topic')
    if not topic:
        topic = raw_task.get('topic', random.choice(SKILL_LIST))
        print(f"format_task_for_db: topic не найден в raw_task, выбран: {topic}")
    return {
        'title': raw_task.get('title', ''),
        'text': raw_task.get('task_text', ''),
        'difficulty': raw_task.get('difficulty', 'easy'),
        'topic': topic, 
        'ideal_solution': raw_task.get('ideal_solution', ''),
        'wrong_solution': raw_task.get('wrong_solution', ''),
        'test_cases': raw_task.get('test_cases', [])
    }
    
def insert_task_to_db(task_data: dict) -> int:
    """Вставка задачи в таблицу Tasks"""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    INSERT INTO Tasks (title, text, difficulty, topic, ideal_solution, wrong_solution, test_cases)
    VALUES (%(title)s, %(text)s, %(difficulty)s, %(topic)s, %(ideal_solution)s, %(wrong_solution)s, %(test_cases)s)
    RETURNING id_task;
    """
    # Преобразуем тесты в JSON
    task_data['test_cases'] = json.dumps(task_data.get('test_cases', []))
    
    cursor.execute(query, task_data)
    task_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    logger.info(f"Задача '{task_data['title']}' добавлена в базу с ID {task_id}")
    return task_id