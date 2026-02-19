# models.py - Database Models for Ramat Utsav (Updated with Rounds Support)

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import CheckConstraint

db = SQLAlchemy()

class Sanskarvarg(db.Model):
    """Sanskarvarg/Organization model"""
    __tablename__ = 'sanskarvarg'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    abbreviation = db.Column(db.String(3), nullable=False, unique=True)
    contact_person_1 = db.Column(db.String(100))
    contact_phone_1 = db.Column(db.String(15))
    contact_person_2 = db.Column(db.String(100))
    contact_phone_2 = db.Column(db.String(15))
    address = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    students = db.relationship('Student', backref='sanskarvarg', lazy=True, cascade='all, delete-orphan')
    counter = db.relationship('StudentCounter', backref='sanskarvarg', uselist=False, cascade='all, delete-orphan')
    submission_statuses = db.relationship('SubmissionStatus', backref='sanskarvarg', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Sanskarvarg {self.name}>'


class Group(db.Model):
    """Group model (A, B, C based on standard ranges)"""
    __tablename__ = 'group'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(10), nullable=False, unique=True)  # 'A', 'B', 'C'
    standard_from = db.Column(db.Integer, nullable=False)
    standard_to = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    students = db.relationship('Student', backref='group', lazy=True)
    game_events = db.relationship('GameEvent', backref='group', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Group {self.name} (Std {self.standard_from}-{self.standard_to})>'
    
    @staticmethod
    def get_group_for_standard(standard):
        """Get the appropriate group for a given standard"""
        return Group.query.filter(
            db.and_(
                Group.standard_from <= standard,
                Group.standard_to >= standard
            )
        ).first()


class Location(db.Model):
    """Location/Venue model"""
    __tablename__ = 'location'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    game_events = db.relationship('GameEvent', backref='location', lazy=True)
    
    def __repr__(self):
        return f'<Location {self.name}>'


class Game(db.Model):
    """Game model (Kho-Kho, 100m Race, Story Telling, etc.)"""
    __tablename__ = 'game'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    game_type = db.Column(db.Enum('Team', 'Individual', 'Baudhik'), nullable=False)
    
    # For Team games only
    min_team_size = db.Column(db.Integer)
    max_team_size = db.Column(db.Integer)
    
    # For Individual/Baudhik games only
    # NULL for Baudhik means "All students in one round"
    capacity_per_round = db.Column(db.Integer)
    
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    game_events = db.relationship('GameEvent', backref='game', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Game {self.name} ({self.game_type})>'
    
    def is_team_game(self):
        """Check if this is a team game"""
        return self.game_type == 'Team'
    
    def needs_rounds(self):
        """Check if this game needs round distribution"""
        return self.game_type in ['Individual', 'Baudhik'] and self.capacity_per_round is not None
    
    def is_baudhik_all(self):
        """Check if this is a Baudhik game with 'All' option (single round)"""
        return self.game_type == 'Baudhik' and self.capacity_per_round is None
    
    __table_args__ = (
        CheckConstraint(
            "(game_type = 'Team' AND min_team_size IS NOT NULL AND max_team_size IS NOT NULL AND capacity_per_round IS NULL) OR "
            "(game_type = 'Individual' AND min_team_size IS NULL AND max_team_size IS NULL AND capacity_per_round IS NOT NULL) OR "
            "(game_type = 'Baudhik' AND min_team_size IS NULL AND max_team_size IS NULL)",
            name='check_game_fields'
        ),
    )


class Student(db.Model):
    """Student model"""
    __tablename__ = 'student'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(20), nullable=False, unique=True)  # XXX-DDMMYYYY-NNN
    name = db.Column(db.String(200), nullable=False)
    gender = db.Column(db.Enum('Male', 'Female'), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    standard = db.Column(db.Integer, nullable=False)
    sanskarvarg_id = db.Column(db.Integer, db.ForeignKey('sanskarvarg.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    participations = db.relationship('Participation', backref='student', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Student {self.student_id} - {self.name}>'


# In your models.py, update the GameEvent class:
# Find this section and add the gender_restriction field

class GameEvent(db.Model):
    """Game Event model (scheduled instances of games)"""
    __tablename__ = 'game_event'
    
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    scheduled_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    status = db.Column(
        db.Enum('Scheduled', 'Ongoing', 'Completed', 'Cancelled'),
        default='Scheduled'
    )
    gender_restriction = db.Column(
        db.Enum('Male', 'Female', 'Mixed'),
        default='Mixed',
        nullable=False
    )  # ADD THIS FIELD
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    participations = db.relationship('Participation', backref='game_event', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<GameEvent {self.game.name} - Group {self.group.name} on {self.scheduled_date}>'
    
    __table_args__ = (
        CheckConstraint('end_time > scheduled_time', name='check_event_times'),
    )
# Update your Participation model in models.py

class Participation(db.Model):
    """Participation model (students participating in game events)"""
    __tablename__ = 'participation'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    game_event_id = db.Column(db.Integer, db.ForeignKey('game_event.id'), nullable=False)
    team_name = db.Column(db.String(100))  # Only for team games
    round_number = db.Column(db.Integer)   # NEW: For individual/baudhik games - assigned round
    registration_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Participation Student:{self.student_id} GameEvent:{self.game_event_id}>'
    
    __table_args__ = (
        db.UniqueConstraint('student_id', 'game_event_id', name='unique_participation'),
    )


class StudentCounter(db.Model):
    """Student Counter model (for generating unique student IDs per sanskarvarg)"""
    __tablename__ = 'student_counter'
    
    sanskarvarg_id = db.Column(db.Integer, db.ForeignKey('sanskarvarg.id'), primary_key=True)
    counter = db.Column(db.Integer, nullable=False, default=0)
    
    def __repr__(self):
        return f'<StudentCounter Sanskarvarg:{self.sanskarvarg_id} Count:{self.counter}>'


class SubmissionStatus(db.Model):
    """Submission Status model (tracks submission status of sanskarvarg-group combinations)"""
    __tablename__ = 'submission_status'
    
    id = db.Column(db.Integer, primary_key=True)
    sanskarvarg_id = db.Column(db.Integer, db.ForeignKey('sanskarvarg.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    is_submitted = db.Column(db.Boolean, default=False, nullable=False)
    submitted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
   # sanskarvarg = db.relationship('Sanskarvarg', backref='submissions')
    group = db.relationship('Group', backref='submissions')
    
    def __repr__(self):
        return f'<SubmissionStatus Sanskarvarg:{self.sanskarvarg_id} Group:{self.group_id} Submitted:{self.is_submitted}>'
    
    __table_args__ = (
        db.UniqueConstraint('sanskarvarg_id', 'group_id', name='unique_submission'),
    )


# Add this class to your models.py file

class EventResult(db.Model):
    """Store results (1st, 2nd, 3rd positions) for each game event"""
    __tablename__ = 'event_result'
    
    id = db.Column(db.Integer, primary_key=True)
    game_event_id = db.Column(db.Integer, db.ForeignKey('game_event.id', ondelete='CASCADE'), nullable=False)
    position = db.Column(db.Integer, nullable=False)  # 1, 2, or 3
    
    # For Individual/Baudhik games - reference the student directly
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=True)
    
    # For Team games - reference sanskarvarg and team name
    sanskarvarg_id = db.Column(db.Integer, db.ForeignKey('sanskarvarg.id', ondelete='CASCADE'), nullable=True)
    team_name = db.Column(db.String(100), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    game_event = db.relationship('GameEvent', backref='results')
    student = db.relationship('Student', backref='individual_results')
    sanskarvarg = db.relationship('Sanskarvarg', backref='team_results')
    
    def get_points(self):
        """Return points for this position (1st=3, 2nd=2, 3rd=1)"""
        points_map = {1: 3, 2: 2, 3: 1}
        return points_map.get(self.position, 0)
    
    def get_display_name(self):
        """Get display name based on game type"""
        if self.student:
            return self.student.name
        elif self.sanskarvarg and self.team_name:
            return f"{self.sanskarvarg.name} - {self.team_name}"
        return "Unknown"
    
    def __repr__(self):
        return f'<EventResult {self.game_event.game.name} - Position {self.position}>'
    


# Add these models at the END of your models.py file

from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    """User model for authentication and authorization"""
    __tablename__ = 'user'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.Enum('UtsavPramukh', 'Sanchalan', 'Vargshikshak'), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    assigned_sanskarvargs = db.relationship('VargshikshakSanskarvarg', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if password matches"""
        return check_password_hash(self.password_hash, password)
    
    def is_utsav_pramukh(self):
        """Check if user is UtsavPramukh (Super Admin)"""
        return self.role == 'UtsavPramukh'
    
    def is_sanchalan(self):
        """Check if user is Sanchalan (Management)"""
        return self.role == 'Sanchalan'
    
    def is_vargshikshak(self):
        """Check if user is Vargshikshak (Teacher)"""
        return self.role == 'Vargshikshak'
    
    def get_assigned_sanskarvarg_ids(self):
        """Get list of sanskarvarg IDs assigned to this Vargshikshak"""
        if not self.is_vargshikshak():
            return []
        return [assignment.sanskarvarg_id for assignment in self.assigned_sanskarvargs]
    
    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class VargshikshakSanskarvarg(db.Model):
    """Mapping table for Vargshikshak to Sanskarvarg assignments"""
    __tablename__ = 'vargshikshak_sanskarvarg'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    sanskarvarg_id = db.Column(db.Integer, db.ForeignKey('sanskarvarg.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    sanskarvarg = db.relationship('Sanskarvarg', backref='vargshikshak_assignments')
    
    def __repr__(self):
        return f'<VargshikshakSanskarvarg User:{self.user_id} Sanskarvarg:{self.sanskarvarg_id}>'
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'sanskarvarg_id', name='unique_mapping'),
    )