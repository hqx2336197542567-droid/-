import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from extensions import db, socketio
from models import User, Question, Answer
import json
import math
import random 
from datetime import datetime, timedelta
import traceback 

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key_123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///classsync.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=60)

db.init_app(app)
socketio.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def calculate_quarter():
    today = datetime.now()
    quarter = (today.month - 1) // 3 + 1
    return f"{today.year}_Q{quarter}"

def grade_logic(q_type, correct_list, student_ans):
    if not correct_list or not student_ans: return False
    s_clean = student_ans.strip()
    for correct_item in correct_list:
        c_clean = correct_item.strip()
        if q_type == 'choice':
            if s_clean.upper() == c_clean.upper(): return True
        elif q_type == 'sort':
            s_list = [x.strip() for x in s_clean.replace('，', ',').split(',')]
            c_list = [x.strip() for x in c_clean.replace('，', ',').split(',')]
            if len(c_list) != len(s_list): continue
            is_match = False
            if len(c_list) < 4:
                if s_list[0] == c_list[0]: is_match = True
            else:
                check_len = math.ceil(len(c_list) * 0.5)
                if s_list[:check_len] == c_list[:check_len]: is_match = True
            if is_match: return True
    return False

@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin: return redirect(url_for('teacher_dashboard'))
        return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if not user:
            is_admin = (username == 'admin')
            user = User(username=username, password=password, is_admin=is_admin)
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=True)
            return redirect(url_for('index'))
        if user.password == password:
            login_user(user, remember=True)
            return redirect(url_for('index'))
        else:
            if username == 'admin': 
                user.password = password
                db.session.commit()
                login_user(user, remember=True)
                return redirect(url_for('index'))
            return render_template('login.html', error="密码错误")
    return render_template('login.html')

@app.route('/teacher')
@login_required
def teacher_dashboard():
    if not current_user.is_admin: return redirect(url_for('index'))
    return render_template('teacher.html')

@app.route('/student')
@login_required
def student_dashboard():
    try:
        stats = json.loads(current_user.stats) if current_user.stats else {}
        achievements = json.loads(current_user.achievements) if current_user.achievements else {}
        current_q_key = calculate_quarter()
        history_records = db.session.query(Answer, Question)\
            .join(Question, Answer.question_id == Question.id)\
            .filter(Answer.student_name == current_user.username)\
            .order_by(Answer.timestamp.desc())\
            .limit(50).all()
        return render_template('student.html', user=current_user, stats=stats, achievements=achievements, current_q_key=current_q_key, history=history_records)
    except:
        return redirect(url_for('logout'))

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

@socketio.on('connect')
def handle_connect(): pass

@socketio.on('get_all_students_stats')
def handle_get_all_stats():
    if not current_user.is_admin: return
    users = User.query.filter_by(is_admin=False).all()
    current_q = calculate_quarter()
    data_list = []
    for u in users:
        stats = json.loads(u.stats) if u.stats else {}
        curr_data = stats.get(current_q, {'total': 0, 'correct': 0})
        curr_rate = round((curr_data['correct'] / curr_data['total'] * 100), 1) if curr_data['total'] > 0 else 0
        all_total = 0
        all_correct = 0
        for q_key, q_val in stats.items():
            all_total += q_val.get('total', 0)
            all_correct += q_val.get('correct', 0)
        all_rate = round((all_correct / all_total * 100), 1) if all_total > 0 else 0
        data_list.append({
            'username': u.username,
            'curr_total': curr_data['total'],
            'curr_correct': curr_data['correct'],
            'curr_rate': curr_rate,
            'all_total': all_total,
            'all_correct': all_correct,
            'all_wrong': all_total - all_correct,
            'all_rate': all_rate
        })
    socketio.emit('all_students_stats_response', data_list, to=request.sid)

@socketio.on('new_question')
def handle_new_question(data):
    if not current_user.is_admin: return
    try:
        q = Question(content=data['content'], question_type=data['type'], options=data.get('options', ''), active_status=True)
        db.session.add(q)
        db.session.commit()
        socketio.emit('receive_question', {'id': q.id, 'content': q.content, 'type': q.question_type, 'options': q.options})
    except: traceback.print_exc()

@socketio.on('submit_answer')
def handle_answer(data):
    try:
        ans = Answer(question_id=data['question_id'], student_name=current_user.username, content=data['content'])
        db.session.add(ans)
        db.session.commit()
        socketio.emit('receive_danmaku', {'student': current_user.username, 'content': data['content']}, to=None)
    except: pass

@socketio.on('simulate_data')
def handle_simulation(data):
    if not current_user.is_admin: return
    q_id = data.get('question_id')
    mode = data.get('mode') 
    question = Question.query.get(q_id)
    if not question: return
    count = 60 if mode == 'random' else 50
    options = ['A', 'B', 'C', 'D']
    if question.options:
        options = [x.strip() for x in question.options.replace('，', ',').split(',')]
    if question.question_type == 'sort': options = ['1,2,3,4', '1,2,4,3', '4,3,2,1', '2,1,3,4']
    for i in range(1, count + 1):
        bot_name = f"Bot_{i:02d}"
        user = User.query.filter_by(username=bot_name).first()
        if not user:
            user = User(username=bot_name, password='123', is_admin=False)
            db.session.add(user)
        content = random.choice(options) if mode == 'random' else options[0]
        ans = Answer(question_id=q_id, student_name=bot_name, content=content)
        db.session.add(ans)
        socketio.emit('receive_danmaku', {'student': bot_name, 'content': content}, to=None)
    db.session.commit()
    socketio.emit('simulation_done', {'count': count})

@socketio.on('stop_and_grade')
def handle_stop_grade(data):
    if not current_user.is_admin: return
    try:
        q_id = data['question_id']
        correct_list = data['correct_answers'] 
        question = Question.query.get(q_id)
        if not question: return
        question.correct_answer = json.dumps(correct_list)
        question.active_status = False
        all_answers = Answer.query.filter_by(question_id=q_id).all()
        latest_answers = {}
        for ans in all_answers: latest_answers[ans.student_name] = ans
        groups = {}
        if question.question_type == 'choice' and question.options:
            for opt in question.options.replace('，', ',').split(','):
                groups[opt.strip().upper()] = []
        sorted_students = sorted(latest_answers.values(), key=lambda x: x.timestamp)
        correct_count = 0
        total_students = len(latest_answers)
        for idx, ans in enumerate(sorted_students):
            user = User.query.filter_by(username=ans.student_name).first()
            if not user: continue
            is_right = grade_logic(question.question_type, correct_list, ans.content)
            ans.is_correct = is_right
            stats = json.loads(user.stats) if user.stats else {}
            achievements = json.loads(user.achievements) if user.achievements else {}
            quarter = calculate_quarter()
            if quarter not in stats: stats[quarter] = {'total': 0, 'correct': 0}
            stats[quarter]['total'] += 1
            if is_right:
                stats[quarter]['correct'] += 1
                correct_count += 1
                user.current_streak = (user.current_streak or 0) + 1
                if idx == 0: achievements['first_blood'] = achievements.get('first_blood', 0) + 1
            else:
                user.current_streak = 0
            if user.current_streak >= 3: achievements['streak_master'] = achievements.get('streak_master', 0) + 1
            total_answered = sum(v['total'] for v in stats.values())
            if total_answered > 0 and total_answered % 10 == 0: achievements['veteran'] = achievements.get('veteran', 0) + 1
            if idx < 5: achievements['fast_talker'] = achievements.get('fast_talker', 0) + 1
            if idx >= total_students - 5 and total_students >= 5: achievements['thinker'] = achievements.get('thinker', 0) + 1
            user.stats = json.dumps(stats)
            user.achievements = json.dumps(achievements)
            content_key = ans.content.strip().upper()
            if content_key not in groups: groups[content_key] = []
            groups[content_key].append({'name': ans.student_name, 'is_correct': is_right})
        db.session.commit()
        display_ans_str = " / ".join(correct_list)
        socketio.emit('grading_complete', {'groups': groups, 'type': question.question_type, 'stats': {'total': total_students, 'correct': correct_count, 'answer': display_ans_str}})
    except Exception as e: traceback.print_exc()

if __name__ == '__main__':
    with app.app_context():
        db.create_all() 
        try:
            if not User.query.filter_by(username='admin').first():
                admin = User(username='admin', password='123', is_admin=True)
                db.session.add(admin)
                db.session.commit()
        except: pass
    # 允许局域网访问
    socketio.run(app, host='0.0.0.0', debug=True, port=5000)

    
