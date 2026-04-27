import os
import json
from datetime import datetime, time
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from geopy.distance import geodesic

app = Flask(__name__)
app.secret_key = 'zcc_secret_key_12345'

# --- 基本設定 ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = '1Xb_tjeB3KbuXSxlwCwVsthRhAPIMKU8SYeiMMkyuEhw' 
RANGE_NAME = '工作表1!A:F' 
SCHOOL_LOCATION = (22.9846, 120.2031)
ALLOWED_DISTANCE_KM = 0.5 

PERIODS = [
    {"name": "第1節", "start": time(8, 0), "end": time(8, 50)},
    {"name": "第2節", "start": time(9, 0), "end": time(9, 50)},
    {"name": "第3節", "start": time(10, 10), "end": time(11, 0)},
    {"name": "第4節", "start": time(11, 10), "end": time(12, 0)},
    {"name": "第5節", "start": time(13, 15), "end": time(14, 5)},
    {"name": "第6節", "start": time(14, 10), "end": time(15, 0)},
    {"name": "第7節", "start": time(15, 10), "end": time(16, 0)},
    {"name": "第8節", "start": time(16, 5), "end": time(16, 55)},
]

def get_sheets_service():
    json_info = os.environ.get('GOOGLE_SHEETS_JSON')
    if not json_info:
        with open('my_key.txt', 'r', encoding='utf-8') as f:
            content = f.read()
            json_info = content[content.find('{'):]
    
    info = json.loads(json_info)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds)

# --- 路由邏輯 ---

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        service = get_sheets_service()
        result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        values = result.get('values', [])[1:]
    except: values = []
    
    summary = {}
    for r in values:
        if len(r) >= 6:
            summary[r[1]] = summary.get(r[1], 0) + int(r[5])
    leaderboard = sorted([{'name': k, 'score': v} for k, v in summary.items()], key=lambda x: x['score'], reverse=True)
    return render_template('index.html', user_name=session['user_name'], leaderboard=leaderboard)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            username = request.form.get('username')
            password = request.form.get('password')
            name = request.form.get('name')
            
            service = get_sheets_service()
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID, 
                range='users!A:C',
                valueInputOption='USER_ENTERED', 
                body={'values': [[username, password, name]]}
            ).execute()
            return jsonify({'status': 'success', 'message': '🎉 註冊成功！'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        service = get_sheets_service()
        result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range='users!A:C').execute()
        users = result.get('values', [])
        for user in users[1:]:
            if user[0] == username and user[1] == password:
                session['user_id'] = user[0]
                session['user_name'] = user[2]
                return jsonify({'status': 'success', 'message': f'歡迎回來，{user[2]}'})
        return jsonify({'status': 'error', 'message': '帳號或密碼錯誤'})
    return render_template('login.html')

@app.route('/submit', methods=['POST'])
def submit():
    if 'user_id' not in session: return jsonify({'status': 'error', 'message': '請先登入'})
    
    now = datetime.now()
    if now.hour >= 17:
        return jsonify({'status': 'error', 'message': '今日簽到已截止 (17:00)'})

    data = request.get_json()
    gps_data = data.get('gps') # 前端傳來的 "lat,lng"
    
    sid = session['user_id']
    name = session['user_name']
    curr_t, curr_d = now.time(), now.strftime("%Y-%m-%d")
    
    this_p, status, score = "非課堂時間", "缺席", 0
    for p in PERIODS:
        if p["start"] <= curr_t <= p["end"]:
            this_p = p["name"]
            diff = (now.hour - p["start"].hour) * 60 + (now.minute - p["start"].minute)
            status, score = ("出席", 10) if diff <= 5 else ("遲到", 5)
            break

    if gps_data:
        try:
            user_loc = tuple(map(float, gps_data.split(',')))
            if geodesic(user_loc, SCHOOL_LOCATION).km > ALLOWED_DISTANCE_KM:
                return jsonify({'status': 'error', 'message': '❌ 距離學校過遠，簽到失敗！'})
        except:
            return jsonify({'status': 'error', 'message': 'GPS 格式錯誤'})

    service = get_sheets_service()
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME,
        valueInputOption='USER_ENTERED', body={'values': [[sid, name, curr_d, this_p, status, score]]}
    ).execute()
    return jsonify({'status': 'success', 'message': f'✅ {name} 簽到成功 ({status})'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)