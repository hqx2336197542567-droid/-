from extensions import db
from flask_login import UserMixin
from datetime import datetime
import json

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    
    # 存储成就 JSON: {"first_blood": 5, "streak_master": 2, ...}
    achievements = db.Column(db.Text, default='{}') 
    
    # 存储季度统计 JSON
    stats = db.Column(db.Text, default='{}')
    
    # 【新增】当前连续答对次数 (用于计算连胜)
    current_streak = db.Column(db.Integer, default=0)

    def get_stats(self):
        return json.loads(self.stats) if self.stats else {}

    def get_achievements(self):
        return json.loads(self.achievements) if self.achievements else {}

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500), nullable=False)
    question_type = db.Column(db.String(20), default='choice')
    options = db.Column(db.String(200), nullable=True)
    correct_answer = db.Column(db.String(500), nullable=True)
    active_status = db.Column(db.Boolean, default=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)

class Answer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'))
    student_name = db.Column(db.String(100))
    content = db.Column(db.String(500))
    is_correct = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)