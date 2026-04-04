import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
import xlwings as xw
import joblib

#def checkprobe(loaded_model ,changrong_features):
#    try:
#        prediction = loaded_model.predict(changrong_features)
#        return prediction
#    except:
#        return 0
    
def checkprobe(loaded_model, changrong_features):
    try:
        # 获取模型预测的概率
        prediction_probabilities = loaded_model.predict_proba(changrong_features)
        # 选择属于类别 1 的概率
        # 假设类别 1 代表“上涨”，它是返回数组的第二列 (索引为 1)
        up_probabilities = prediction_probabilities[:, 1]
        return up_probabilities
    except Exception as e:
        print(f"Error: {e}")
        return 0



# Update file paths with escaped backslashes
def learn():
#    system_data_path = 'C:\\STOCK\\SYSTEM.xlsx'
    try:
#        system_data_path = 'C:\\STOCK\\GOD_Update.xlsx'
        system_data_path = 'C:\\STOCK\\SYSTEM_HANK.xlsx'
        history_data_path = 'C:\\STOCK\\History.xlsx'
        app = xw.App(visible=True)
        # Reload the data
        system_data = pd.read_excel(system_data_path)
        history_data = pd.read_excel(history_data_path)
        wb = xw.Book(system_data_path)
        # Handling missing values in categorical columns
        categorical_columns = ['股票性質', '現況分類']
        for column in categorical_columns:
            history_data[column].fillna("unknown", inplace=True)  # Replace missing values with 'unknown'

        # Create binary features from '狀態' column
        history_data['爆'] = history_data['狀態'].str.contains('爆').fillna(False).astype(int)
        history_data['寬紫'] = history_data['狀態'].str.contains('寬紫').fillna(False).astype(int)
        history_data['嚴紫'] = history_data['狀態'].str.contains('嚴紫').fillna(False).astype(int)

        # Apply label encoding to categorical columns
        label_encoder = LabelEncoder()
        for column in categorical_columns:
            history_data[column] = label_encoder.fit_transform(history_data[column].astype(str))

        # Define model features and prepare data
        model_features = ['股票性質', '現況分類', 'FVG+', 'FVG-', 'PER', 'ROE', '爆', '寬紫', '嚴紫']
        model_data = history_data.dropna(subset=model_features)

        # Preparing the target variable


        # Save the model as a .joblib file
        model_filename = 'C:\\STOCK\\random_forest_model.joblib'


        # Load the model from the .joblib file
        loaded_model = joblib.load(model_filename)

        valid_labels = set(label_encoder.classes_)

        # Iterate over each row in the system_data
        for index, changrong_data in system_data.iterrows():
            # Check if the '股票名稱' is present in history_data
        #    if not all(col in changrong_data for col in model_features):
        #        print(f"Skipping record for '{changrong_data['股票名稱']}' due to missing columns.")
        #        continue  # 跳过当前记录
            if changrong_data['股票名稱'] not in model_data['股票名稱'].values:
        #        print(f"No historical data found for '{changrong_data['股票名稱']}'")
                continue  # Skip if no historical data is available
            if changrong_data['股票性質'] not in valid_labels:
                changrong_data['股票性質'] = 'unknown'
        #    print(index, changrong_data)
            # Apply the same preprocessing as for the training data
            changrong_data['股票性質'] = label_encoder.transform([changrong_data['股票性質']])[0]
            changrong_data['現況分類'] = label_encoder.transform([changrong_data['現況分類']])[0]
            changrong_data['爆'] = int('爆' in changrong_data['狀態'])
            changrong_data['寬紫'] = int('寬紫' in changrong_data['狀態'])
            changrong_data['嚴紫'] = int('嚴紫' in changrong_data['狀態'])

            changrong_features = changrong_data[model_features].values.reshape(1, -1)

            # Predict using the loaded model
            probevalue = checkprobe(loaded_model ,changrong_features)
            
        #    print(f"Prediction for '{changrong_data['股票名稱']}': {probevalue}")
        #    print(index, str(index + 2))
        #    system_data.at[index , 'AY']= probevalue

            print(probevalue)
            wb.sheets['SYSTEM'].range("AY" + str(index + 2)).value = probevalue
        #   system_data.to_excel('C:\\STOCK\\SYSTEM.xlsx', index=False, engine='openpyxl')
            
        wb.save()
        wb.close()
        app.quit()
    except:
        print("ERR")
        return 0

if __name__ == '__main__':
#    get_setting()
    learn()
#     power("2330")
