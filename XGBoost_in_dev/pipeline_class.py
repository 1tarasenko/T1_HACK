import numpy as np
import xgboost as xgb


class PredictionPipeline:
    def __init__(self, model, feature_names):
        """
        model: обученная XGBoost-модель (XGBClassifier, XGBRegressor или Booster)
        feature_names: список строк — имена признаков в том порядке, в каком модель их ожидает
        """
        self.model = model
        self.feature_names = feature_names

    def predict(self, input_dict):
        """
        Принимает словарь вида {"age": 25, "income": 50000, ...}
        Возвращает предсказание в удобном формате.
        """
        # Проверка: все ли нужные признаки есть во входных данных?
        missing = set(self.feature_names) - set(input_dict.keys())
        if missing:
            raise ValueError(f"Отсутствуют признаки: {missing}")

        # Собираем значения в правильном порядке
        # Например: input_dict = {"income":50000, "age":25} → [25, 50000] если feature_names=["age","income"]
        input_values = [input_dict[feat] for feat in self.feature_names]

        # Преобразуем в numpy-массив формы (1, n_features)
        X = np.array(input_values, dtype=np.float32).reshape(1, -1)

        # Делаем предсказание
        if hasattr(self.model, "predict_proba"):
            # Это, скорее всего, XGBClassifier из sklearn-API
            pred_class = self.model.predict(X)[0]
            pred_proba = self.model.predict_proba(X)[0]
            return round(pred_proba[1] * 100, 2)
        
        elif hasattr(self.model, "predict"):
            # Это может быть XGBRegressor или нативный Booster
            pred = self.model.predict(X)[0]
            return {
                "prediction": float(pred)
            }
        else:
            raise TypeError("Модель не поддерживает метод predict")