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
    {"name": "第8節", "start": time(16, 5), "end": time(20, 55)},
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

# --- 路由 ---

@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    try:
        service = get_sheets_service()
        result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        values = result.get('values', [])[1:]
    except: values = []
    
    summary = {}
    for r in values:
        if len(r) >= 6: summary[r[1]] = summary.get(r[1], 0) + int(r[5])
    leaderboard = sorted([{'name': k, 'score': v} for k, v in summary.items()], key=lambda x: x['score'], reverse=True)
    return render_template('index.html', user_name=session['user_name'], leaderboard=leaderboard)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uid, pwd = request.form.get('username'), request.form.get('password')
        service = get_sheets_service()
        users = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range='users!A:C').execute().get('values', [])
        for u in users[1:]:
            if u[0] == uid and u[1] == pwd:
                session['user_id'], session['user_name'] = u[0], u[2]
                return jsonify({'status': 'success'})
        return jsonify({'status': 'error', 'message': '帳號或密碼錯誤'})
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uid, pwd, name = request.form.get('username'), request.form.get('password'), request.form.get('name')
        try:
            service = get_sheets_service()
            service.spreadsheets().values().append(spreadsheetId=SPREADSHEET_ID, range='users!A:C', 
                valueInputOption='USER_ENTERED', body={'values': [[uid, pwd, name]]}).execute()
            return jsonify({'status': 'success', 'message': '註冊成功！'})
        except Exception as e: return jsonify({'status': 'error', 'message': str(e)})
    return render_template('register.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        uid, name, new_pwd = request.form.get('username'), request.form.get('name'), request.form.get('new_password')
        service = get_sheets_service()
        users = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range='users!A:C').execute().get('values', [])
        for i, u in enumerate(users):
            if i > 0 and u[0] == uid and u[2] == name:
                service.spreadsheets().values().update(spreadsheetId=SPREADSHEET_ID, range=f'users!B{i+1}', 
                    valueInputOption='USER_ENTERED', body={'values': [[new_pwd]]}).execute()
                return jsonify({'status': 'success'})
        return jsonify({'status': 'error', 'message': '驗證資訊不正確'})
    return render_template('forgot_password.html')

@app.route('/my_records')
def my_records():
    if 'user_id' not in session: return jsonify([])
    try:
        service = get_sheets_service()
        result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        values = result.get('values', [])
        user_history = [{'date': r[2], 'period': r[3], 'status': r[4]} for r in values[1:] if r[0] == session['user_id']]
        return jsonify(user_history[::-1]) # 最新的在前
    except: return jsonify([])

@app.route('/submit', methods=['POST'])
def submit():
    if 'user_id' not in session: return jsonify({'status': 'error'})
    now = datetime.now()
    if now.hour >= 17: return jsonify({'status': 'error', 'message': '今日簽到已截止'})
    
    data = request.get_json()
    gps = data.get('gps')
    if gps:
        user_loc = tuple(map(float, gps.split(',')))
        if geodesic(user_loc, SCHOOL_LOCATION).km > ALLOWED_DISTANCE_KM:
            return jsonify({'status': 'error', 'message': '距離學校太遠囉！'})

    curr_t, curr_d = now.time(), now.strftime("%Y-%m-%d")
    this_p, status, score = "非課堂時間", "缺席", 0
    for p in PERIODS:
        if p["start"] <= curr_t <= p["end"]:
            this_p = p["name"]
            diff = (now.hour - p["start"].hour)*60 + (now.minute - p["start"].minute)
            status, score = ("出席", 10) if diff <= 5 else ("遲到", 5)
            break

    service = get_sheets_service()
    service.spreadsheets().values().append(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME,
        valueInputOption='USER_ENTERED', body={'values': [[session['user_id'], session['user_name'], curr_d, this_p, status, score]]}).execute()
    return jsonify({'status': 'success', 'message': f'簽到成功 ({status})'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))