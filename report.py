import logging
from db import get_db_connection
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_user_report(user_id: str, llm_client=None) -> dict:
    """Генерация отчета о навыках пользователя
    Использует ТОЛЬКО данные из БД
    - Уровни навыков → из таблицы UserSkills
    - Статистика по попыткам → из UserProgress + UserFeedback
    - Подсказки → из UserFeedback.hints_used_count
    
    Возвращает dict с полями:
      - user_id, overall_grade
      - strengths[], weaknesses[] → для LLM-промпта
      - summary: total_attempts, successful_attempts, total_hints_used
      - human_feedback 
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем внутренний id_user из Users по внешнему user_id 
    cursor.execute("SELECT id_user FROM Users WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return {"error": "User not found"}
    id_user = row[0]
    
    # Основной запрос для сбора статистики
    cursor.execute("""
        WITH user_stats AS (
            -- Статистика по попыткам и подсказкам
            SELECT 
                COUNT(*) AS total_attempts,
                COUNT(*) FILTER (WHERE up.status = 'success' AND uf.correct = true) AS successful_attempts,
                COALESCE(SUM(uf.hints_used_count), 0) AS total_hints
            FROM UserProgress up
            JOIN UserFeedback uf ON uf.id_user_progress = up.id
            WHERE up.id_user = %s
        ),
        user_skills AS (
            -- Навыки пользователя
            SELECT skill_name, skill_level FROM UserSkills WHERE id_user = %s
        ),
        code_metrics AS (
            -- Метрики качества кода
            SELECT 
                COALESCE(AVG(uf.style), 0) AS avg_style,
                COALESCE(AVG(uf.pep8), 0) AS avg_pep8,
                COALESCE(AVG(uf.optimal), 0) AS avg_optimal,
                COALESCE(AVG(uf.chatgpt_style), 0) AS avg_chatgpt_style,
                COUNT(*) FILTER (
                    WHERE uf.time_complexity ILIKE '%%n^2%%' 
                       OR uf.time_complexity ILIKE '%%n^3%%'
                       OR uf.time_complexity ILIKE '%%2^n%%'
                       OR uf.time_complexity ILIKE '%%n^3%%' 
                       OR uf.time_complexity ILIKE '%%2^n%%' 
                       OR uf.time_complexity ILIKE '%%n²%%' 
                       OR uf.time_complexity ILIKE '%%n³%%' 
                       OR uf.time_complexity ILIKE '%%n!%%' 
                       OR uf.time_complexity ILIKE '%%exponential%%' 
                       OR uf.time_complexity ILIKE '%%factorial%%' 
                       OR uf.time_complexity ILIKE '%%O(n^2)%%' 
                       OR uf.time_complexity ILIKE '%%O(n^3)%%' 
                       OR uf.time_complexity ILIKE '%%O(2^n)%%' 
                ) AS nonoptimal_count
            FROM UserFeedback uf
            JOIN UserProgress up ON uf.id_user_progress = up.id
            WHERE up.id_user = %s
        )
        SELECT 
            s.total_attempts, 
            s.successful_attempts, 
            s.total_hints,
            c.avg_style, 
            c.avg_pep8, 
            c.avg_optimal, 
            c.avg_chatgpt_style,
            c.nonoptimal_count,
            sk.skill_name, 
            sk.skill_level
        FROM user_stats s
        CROSS JOIN code_metrics c
        LEFT JOIN user_skills sk ON true
        ORDER BY sk.skill_level ASC NULLS LAST;
    """, (id_user, id_user, id_user))
    
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return {"error": "No data found for user"}
    
    # Извлекаем общую статистику
    first_row = rows[0]
    total_attempts = first_row[0] or 0
    successful_attempts = first_row[1] or 0
    total_hints = first_row[2] or 0
    avg_style = round(first_row[3], 2)
    avg_pep8 = round(first_row[4], 2)
    avg_optimal = round(first_row[5], 2)
    avg_chatgpt_style = round(first_row[6], 2)
    nonoptimal_count = int(first_row[7] or 0)
    
    # Собираем навыки
    skills_data = [(row[8], row[9]) for row in rows if row[8] and row[9] is not None]
    
    # Формирование strengths и weaknesses
    # Используется пороговая логика BKT:
    strengths = []
    weaknesses = []
    for skill_name, level in skills_data:
        if level >= 0.7:
            strengths.append({"skill": skill_name, "level": round(level, 2)})
        elif level <= 0.4:
            weaknesses.append({"skill": skill_name, "level": round(level, 2)})
    
    # Рассчитываем средний уровень навыков
    if skills_data:
        avg_skill_level = sum(level for _, level in skills_data) / len(skills_data)
    else:
        avg_skill_level = 0.0
    
    # Определяем общий уровень
    if avg_skill_level >= 0.8:
        grade = "Expert"
    elif avg_skill_level >= 0.6:
        grade = "Advanced"
    elif avg_skill_level >= 0.4:
        grade = "Intermediate"
    elif avg_skill_level >= 0.2:
        grade = "Beginner"
    else:
        grade = "New"
    
    # Формируем базовый отчет
    report = {
        "user_id": user_id,     # Идентификатор пользователя
        "overall_grade": grade, # Общий уровень пользователя, определяемый на основе среднего уровня навыков
        # Возможные значения: "Expert", "Advanced", "Intermediate", "Beginner", "New"
        "strengths": strengths, # Список сильных навыков пользователя (уровень >= 0.7)
        # Каждый элемент - словарь с ключами 'skill' (название навыка) и 'level' (уровень)
        "weaknesses": weaknesses, # Список слабых навыков пользователя (уровень <= 0.4)
        "summary": {
            "total_attempts": total_attempts,  # Общее количество попыток решения задач
            "successful_attempts": successful_attempts, # Количество успешных решений
            "total_hints_used": total_hints, # Общее количество использованных подсказок
        },
        "code_quality_metrics": {
            "avg_style": avg_style, # Средняя оценка стиля кода
            "avg_pep8": avg_pep8, # Средняя оценка соответствия кода стандарту PEP8
            "avg_optimal": avg_optimal, # Средняя оценка оптимальности решения
            "avg_chatgpt_style": avg_chatgpt_style, 
            "nonoptimal_complexity_count": nonoptimal_count # Количество задач, в которых LLM обнаружил неоптимальную сложность
        }
    }
    print("Сформированный отчет:", report) # Отладка
    
    # Генерация human_feedback с помощью LLM
    if llm_client:
        str_str = ", ".join(s["skill"] for s in strengths) or "пока не выявлены"
        str_weak = ", ".join(w["skill"] for w in weaknesses) or "пока нет явных проблем"
        prompt = (
            f"Пользователь {user_id}. Уровень: {grade}. "
            f"Сильные стороны: {str_str}. Слабые стороны: {str_weak}. "
            f"Решено задач: {total_attempts}, из них успешных: {successful_attempts}. "
            f"Использовано подсказок: {total_hints}. "
            f"Качество кода: стиль {avg_style:.2f}, PEP8 {avg_pep8:.2f}, оптимальность {avg_optimal:.2f}."
        )
        # Добавляем информацию о ChatGPT_style в промпт
        prompt += f" Признаки использования (вероятность) ИИ при написании кода (ChatGPT_style): {avg_chatgpt_style:.2f}. "
        
        if nonoptimal_count > 0:
            prompt += f" Обращаю внимание: в {nonoptimal_count} задачах использована неоптимальная сложность (O(n²) и выше)."

        try:
            resp = llm_client.chat.completions.create(
                model="qwen3-32b-awq",
                messages=[
                    {"role": "system", "content": "/no_think Ты — наставник по Python. Говоришь поддержкающе, конкретно, без воды, но по фактам"},
                    {"role": "user", "content": f"На основе следующих данных сформулируй краткий (3–4 предложения), мотивирующий фидбек на русском:\n{prompt}\nОтвет без заголовков, просто текст. Оппиши все сильнные или слабые стороны, в каких темах нужно работать!"}
                ],
                temperature=0.5,
                max_tokens=250
            )
            report["human_feedback"] = resp.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"LLM feedback failed: {e}")
            report["human_feedback"] = "Продолжайте в том же духе!"
    return report