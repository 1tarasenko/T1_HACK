class BKT:
    """
    Класс для моделирования уровня навыков с помощью Bayesian Knowledge Tracing (BKT)
    """
    def __init__(self, pL0=0.5, pT=0.1, pS=0.15, pG=0.05):
        """
        Инициализация BKT модели:
        Аргументы:
            pL0 - начальная вероятность знания навыка (0.5 по умолчанию) - знает / не знает 
            pT - вероятность обучения между задачами (0.1 по умолчанию)
            pS - вероятность ошибки при знании (0.15 по умолчанию)
            pG - вероятность угадывания при отсутствии знания (0.05 по умолчанию)
        """
        self.pL0 = pL0
        self.pT = pT
        self.pS = pS
        self.pG = pG
        self.state = {}

    def update(self, skill: str, correct: bool) -> float:
        """
        Обновление вероятности знания навыка после решения задачи:
        Аргументы:
            skill - название навыка
            correct - успешно ли решена задача
        Возвращает новую вероятность знания навыка
        """
        # Берём текущую вероятность знания навыка (если нет — pL0 = 0.5)
        pL = self.state.get(skill, self.pL0)
        
        # Обновление по формуле BKT
        if correct:
            # справился - повышаем вероятность знания
            pL_post = (pL * (1 - self.pS)) / (pL * (1 - self.pS) + (1 - pL) * self.pG)
            # ограничиваем рост: не больше, чем на 0.15 за раз
            pL_post = min(pL + 0.15, pL_post)
        else:
            # ошибка - понижаем вероятность знания
            pL_post = (pL * self.pS) / (pL * self.pS + (1 - pL) * (1 - self.pG))
        # Обучение
        pL_new = pL_post + (1 - pL_post) * self.pT
        # Не даём вероятности выйти за 1.0 (ограничиваем)
        self.state[skill] = min(1.0, pL_new)
        return self.state[skill]

    def get_recommendation_skill(self) -> str:
        """
        Получение навыка с минимальной вероятностью знания для рекомендации
        цели адаптивного обучения — фокусироваться на слабых местах
        Возвращает:
            Название навыка с минимальной вероятностью
        """
        if not self.state:
            # Если состояние пустое, возвращаем None
            return None
        
        # Находим навык с минимальной вероятностью
        min_skill = min(self.state, key=self.state.get)
        return min_skill

    def get_recommended_difficulty_range(self, skill: str) -> tuple[float, float]:
        """
        Получение рекомендуемого диапазона сложности для навыка:
        Аргументы:
            skill - название навыка
        Возвравщает:
            Кортеж (минимальная сложность, максимальная сложность)
        """
        current_level = self.state.get(skill, self.pL0)
        # оценивает подходящий диапазон сложности на основе текущего уровня навыка
        # Если уровень низкий - даем легкие задачи, если высокий - сложнее
        if current_level < 0.3:
            min_diff, max_diff = 0.1, 0.3   # easy
        elif current_level < 0.6:
            min_diff, max_diff = 0.2, 0.5   # easy-medium
        elif current_level < 0.8:
            min_diff, max_diff = 0.5, 0.7   # medium
        elif current_level < 0.95:
            min_diff, max_diff = 0.7, 0.9   # medium-hard
        else:
            min_diff, max_diff = 0.8, 1.0   # hard
        
        # min_diff не превышает max_diff после расчета 
        if min_diff > max_diff:
            min_diff = max_diff
        
        return min_diff, max_diff