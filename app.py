# app.py - Complete with Groups, Sanskarvargs, and Locations CRUD

from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
from datetime import datetime, date
import os
import re
from functools import wraps
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv


# Import models
from models import EventResult, db, Sanskarvarg, Group, Location, Game, Student, GameEvent, Participation, StudentCounter, SubmissionStatus, User, VargshikshakSanskarvarg
# Initialize Flask app
app = Flask(__name__)

# Configuration
load_dotenv()

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'fallback-key')
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = False  # Turn off in production

# Initialize db with app
db.init_app(app)

# ============= HELPER FUNCTIONS =============


def validate_team_sizes(sanskarvarg_id, group_id, all_students_data):
    """
    Validate that all teams have correct number of players (min-max range)
    Returns: {'valid': True/False, 'errors': [...]}
    """
    errors = []
    
    # Get all game events for this group
    game_events = GameEvent.query.filter_by(group_id=group_id).all()
    
    # Group students by team for each team game
    for event in game_events:
        game = event.game
        
        if not game.is_team_game():
            continue
        
        # Count students per team for this game event
        teams = {}
        for student_data in all_students_data:
            for game_data in student_data.get('games', []):
                if game_data['game_event_id'] == event.id:
                    team_name = game_data.get('team_name')
                    if team_name:
                        teams[team_name] = teams.get(team_name, 0) + 1
        
        # Validate each team
        for team_name, count in teams.items():
            if count < game.min_team_size:
                errors.append(f'{game.name}: Team "{team_name}" has {count} player(s), minimum required is {game.min_team_size}')
            elif count > game.max_team_size:
                errors.append(f'{game.name}: Team "{team_name}" has {count} player(s), maximum allowed is {game.max_team_size}')
    
    return {
        'valid': len(errors) == 0,
        'errors': errors
    }

def distribute_students_to_rounds(total_students, capacity_per_round):
    """
    Distribute students evenly across rounds to minimize variance.
    
    Args:
        total_students: Total number of students
        capacity_per_round: Maximum students per round
    
    Returns:
        List of student counts per round
    
    Examples:
        distribute_students_to_rounds(35, 8) → [7, 7, 7, 7, 7]  (5 rounds of 7 each)
        distribute_students_to_rounds(20, 8) → [7, 7, 6]        (3 rounds: 7, 7, 6)
        distribute_students_to_rounds(30, 8) → [8, 8, 7, 7]     (4 rounds: 8, 8, 7, 7)
    """
    if total_students == 0:
        return []
    
    # Calculate minimum number of rounds needed
    num_rounds = (total_students + capacity_per_round - 1) // capacity_per_round
    
    # Calculate base size and how many rounds need one extra student
    base_size = total_students // num_rounds
    extra_students = total_students % num_rounds
    
    # Create round distribution
    rounds = []
    for i in range(num_rounds):
        if i < extra_students:
            rounds.append(base_size + 1)
        else:
            rounds.append(base_size)
    
    return rounds

def generate_abbreviation(name, existing_abbreviations=None):
    """
    Generate a unique 3-letter abbreviation from a name.
    
    Algorithm:
    1. Try first 3 letters
    2. Try first 2 letters + last letter
    3. Try first letter + last 2 letters
    4. Try consonants only
    5. Add numbers if needed (AB1, AB2, etc.)
    """
    if existing_abbreviations is None:
        existing_abbreviations = set()
    
    # Clean the name - remove special characters, keep only letters
    clean_name = re.sub(r'[^a-zA-Z]', '', name).upper()
    
    if len(clean_name) < 2:
        clean_name = name.upper()[:3].ljust(3, 'X')
    
    # Strategy 1: First 3 letters
    abbr = clean_name[:3].ljust(3, 'X')
    if abbr not in existing_abbreviations:
        return abbr
    
    # Strategy 2: First 2 + last letter
    if len(clean_name) >= 3:
        abbr = clean_name[0:2] + clean_name[-1]
        if abbr not in existing_abbreviations:
            return abbr
    
    # Strategy 3: First + last 2 letters
    if len(clean_name) >= 3:
        abbr = clean_name[0] + clean_name[-2:]
        if abbr not in existing_abbreviations:
            return abbr
    
    # Strategy 4: Consonants only
    consonants = ''.join([c for c in clean_name if c not in 'AEIOU'])
    if len(consonants) >= 3:
        abbr = consonants[:3]
        if abbr not in existing_abbreviations:
            return abbr
    
    # Strategy 5: Add numbers
    base_abbr = clean_name[:2].ljust(2, 'X')
    for i in range(1, 100):
        abbr = base_abbr + str(i)
        if abbr not in existing_abbreviations:
            return abbr
    
    # Fallback
    return clean_name[:3].ljust(3, 'X')

def check_standard_range_overlap(standard_from, standard_to, exclude_group_id=None):
    """
    Check if a standard range overlaps with existing groups.
    Returns (is_valid, error_message)
    """
    query = Group.query
    if exclude_group_id:
        query = query.filter(Group.id != exclude_group_id)
    
    existing_groups = query.all()
    
    for group in existing_groups:
        # Check if ranges overlap
        if not (standard_to < group.standard_from or standard_from > group.standard_to):
            return False, f"Standard range overlaps with Group '{group.name}' (Std {group.standard_from}-{group.standard_to})"
    
    return True, None



# ============= AUTHENTICATION DECORATORS =============

def login_required(f):
    """Decorator to require login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*roles):
    """Decorator to require specific role(s)"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please login to access this page', 'error')
                return redirect(url_for('login'))
            
            user = User.query.get(session['user_id'])
            if not user or not user.is_active:
                session.clear()
                flash('Your account is inactive', 'error')
                return redirect(url_for('login'))
            
            if user.role not in roles:
                flash('You do not have permission to access this page', 'error')
                return redirect(url_for('index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def get_current_user():
    """Get currently logged in user"""
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None


# ============= AUTHENTICATION ROUTES =============

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    # If already logged in, redirect to home
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('Please enter both username and password', 'error')
            return redirect(url_for('login'))
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            if not user.is_active:
                flash('Your account is inactive. Please contact administrator.', 'error')
                return redirect(url_for('login'))
            
            # Set session
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            session['full_name'] = user.full_name
            
            flash(f'Welcome, {user.full_name}!', 'success')
            
            # Redirect based on role
            if user.is_vargshikshak():
                return redirect(url_for('register_students'))
            else:
                return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'error')
            return redirect(url_for('login'))
    
    return render_template('auth/login.html')


@app.route('/logout')
def logout():
    """Logout"""
    session.clear()
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('login'))


# ============= USER MANAGEMENT ROUTES (UtsavPramukh only) =============

@app.route('/users')
@login_required
@role_required('UtsavPramukh')
def list_users():
    """List all users (UtsavPramukh only)"""
    users = User.query.order_by(User.created_at.desc()).all()
    
    # Get sanskarvarg assignments for each Vargshikshak
    user_data = []
    for user in users:
        assigned_sanskarvargs = []
        if user.is_vargshikshak():
            assigned_sanskarvargs = [
                assignment.sanskarvarg.name 
                for assignment in user.assigned_sanskarvargs
            ]
        
        user_data.append({
            'user': user,
            'assigned_sanskarvargs': assigned_sanskarvargs
        })
    
    return render_template('users/list.html', user_data=user_data)


@app.route('/users/create', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh')
def create_user():
    """Create new user (UtsavPramukh only)"""
    if request.method == 'POST':
        try:
            username = request.form.get('username')
            password = request.form.get('password')
            full_name = request.form.get('full_name')
            role = request.form.get('role')
            
            # Validation
            if not username or not password or not full_name or not role:
                flash('All fields are required', 'error')
                return redirect(url_for('create_user'))
            
            # Check if username already exists
            existing_user = User.query.filter_by(username=username).first()
            if existing_user:
                flash('Username already exists', 'error')
                return redirect(url_for('create_user'))
            
            # Create user
            user = User(
                username=username,
                full_name=full_name,
                role=role,
                is_active=True
            )
            user.set_password(password)
            
            db.session.add(user)
            db.session.flush()  # Get user ID
            
            # If Vargshikshak, assign sanskarvargs
            if role == 'Vargshikshak':
                sanskarvarg_ids = request.form.getlist('sanskarvarg_ids')
                
                if not sanskarvarg_ids:
                    flash('Please assign at least one Sanskarvarg to Vargshikshak', 'error')
                    db.session.rollback()
                    return redirect(url_for('create_user'))
                
                for sanskarvarg_id in sanskarvarg_ids:
                    assignment = VargshikshakSanskarvarg(
                        user_id=user.id,
                        sanskarvarg_id=int(sanskarvarg_id)
                    )
                    db.session.add(assignment)
            
            db.session.commit()
            
            flash(f'User "{username}" created successfully!', 'success')
            return redirect(url_for('list_users'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating user: {str(e)}', 'error')
            return redirect(url_for('create_user'))
    
    # GET request
    sanskarvargs = Sanskarvarg.query.order_by(Sanskarvarg.name).all()
    return render_template('users/create.html', sanskarvargs=sanskarvargs)


@app.route('/users/delete/<int:id>', methods=['POST'])
@login_required
@role_required('UtsavPramukh')
def delete_user(id):
    """Delete user (UtsavPramukh only)"""
    try:
        user = User.query.get_or_404(id)
        
        # Prevent deleting yourself
        current_user = get_current_user()
        if user.id == current_user.id:
            flash('You cannot delete your own account!', 'error')
            return redirect(url_for('list_users'))
        
        username = user.username
        db.session.delete(user)
        db.session.commit()
        
        flash(f'User "{username}" deleted successfully', 'success')
        return redirect(url_for('list_users'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'error')
        return redirect(url_for('list_users'))


@app.route('/users/toggle-status/<int:id>', methods=['POST'])
@login_required
@role_required('UtsavPramukh')
def toggle_user_status(id):
    """Activate/deactivate user (UtsavPramukh only)"""
    try:
        user = User.query.get_or_404(id)
        
        # Prevent deactivating yourself
        current_user = get_current_user()
        if user.id == current_user.id:
            flash('You cannot deactivate your own account!', 'error')
            return redirect(url_for('list_users'))
        
        user.is_active = not user.is_active
        db.session.commit()
        
        status = 'activated' if user.is_active else 'deactivated'
        flash(f'User "{user.username}" {status} successfully', 'success')
        return redirect(url_for('list_users'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating user status: {str(e)}', 'error')
        return redirect(url_for('list_users'))

# ============= MAIN ROUTES =============

@app.route('/')
@login_required
def index():
    """Main dashboard/index page"""
    current_user = get_current_user()
    
    # If Vargshikshak, redirect directly to registration
    if current_user.is_vargshikshak():
        return redirect(url_for('register_students'))
    
    return render_template('index.html', current_user=current_user)


# ============= GAMES ROUTES =============

@app.route('/games')
@login_required
@role_required('UtsavPramukh', 'Sanchalan')

def list_games():
    """List all games"""
    games = Game.query.order_by(Game.game_type, Game.name).all()
    return render_template('games/list.html', games=games)

@app.route('/games/create', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def create_game():
    """Create a new game"""
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            game_type = request.form.get('game_type')
            description = request.form.get('description')
            
            min_team_size = None
            max_team_size = None
            capacity_per_round = None
            
            if game_type == 'Team':
                min_team_size = int(request.form.get('min_team_size'))
                max_team_size = int(request.form.get('max_team_size'))
                
                if min_team_size > max_team_size:
                    flash('Minimum team size cannot be greater than maximum team size!', 'error')
                    return redirect(url_for('create_game'))
            
            elif game_type == 'Individual':
                capacity_value = request.form.get('capacity_per_round')
                if not capacity_value:
                    flash('Capacity per round is required for Individual games!', 'error')
                    return redirect(url_for('create_game'))
                capacity_per_round = int(capacity_value)
            
            elif game_type == 'Baudhik':
                capacity_type = request.form.get('baudhik_capacity_type')
                if capacity_type == 'limited':
                    capacity_value = request.form.get('baudhik_capacity_value')
                    if capacity_value:
                        capacity_per_round = int(capacity_value)
            
            game = Game(
                name=name,
                game_type=game_type,
                min_team_size=min_team_size,
                max_team_size=max_team_size,
                capacity_per_round=capacity_per_round,
                description=description
            )
            
            db.session.add(game)
            db.session.commit()
            
            flash(f'Game "{name}" created successfully!', 'success')
            return redirect(url_for('list_games'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating game: {str(e)}', 'error')
            return redirect(url_for('create_game'))
    
    return render_template('games/create.html')

@app.route('/games/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def edit_game(id):
    """Edit an existing game"""
    game = Game.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            description = request.form.get('description')
            
            game.name = name
            game.description = description
            
            if game.game_type == 'Team':
                min_team_size = int(request.form.get('min_team_size'))
                max_team_size = int(request.form.get('max_team_size'))
                
                if min_team_size > max_team_size:
                    flash('Minimum team size cannot be greater than maximum team size!', 'error')
                    return redirect(url_for('edit_game', id=id))
                
                game.min_team_size = min_team_size
                game.max_team_size = max_team_size
            
            elif game.game_type == 'Individual':
                capacity_value = request.form.get('capacity_per_round')
                if not capacity_value:
                    flash('Capacity per round is required for Individual games!', 'error')
                    return redirect(url_for('edit_game', id=id))
                game.capacity_per_round = int(capacity_value)
            
            elif game.game_type == 'Baudhik':
                capacity_type = request.form.get('baudhik_capacity_type')
                if capacity_type == 'limited':
                    capacity_value = request.form.get('baudhik_capacity_value')
                    if capacity_value:
                        game.capacity_per_round = int(capacity_value)
                else:
                    game.capacity_per_round = None
            
            db.session.commit()
            
            flash(f'Game "{name}" updated successfully!', 'success')
            return redirect(url_for('list_games'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating game: {str(e)}', 'error')
            return redirect(url_for('edit_game', id=id))
    
    return render_template('games/edit.html', game=game)

@app.route('/games/delete/<int:id>', methods=['POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def delete_game(id):
    """Delete a game and all related events"""
    try:
        game = Game.query.get_or_404(id)
        game_name = game.name
        event_count = GameEvent.query.filter_by(game_id=id).count()
        
        db.session.delete(game)
        db.session.commit()
        
        if event_count > 0:
            flash(f'Game "{game_name}" and {event_count} related event(s) deleted successfully!', 'warning')
        else:
            flash(f'Game "{game_name}" deleted successfully!', 'success')
        
        return redirect(url_for('list_games'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting game: {str(e)}', 'error')
        return redirect(url_for('list_games'))





# ============= GAME EVENTS ROUTES =============

@app.route('/game-events')
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def list_game_events():
    """List all game events"""
    game_events = GameEvent.query.order_by(GameEvent.scheduled_date, GameEvent.scheduled_time).all()
    return render_template('game_events/list.html', game_events=game_events)


@app.route('/game-events/create', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def create_game_event():
    """Create a new game event"""
    if request.method == 'POST':
        try:
            game_id = int(request.form.get('game_id'))
            group_id = int(request.form.get('group_id'))
            location_id = int(request.form.get('location_id'))
            gender_restriction = request.form.get('gender_restriction')  # NEW
            scheduled_date_str = request.form.get('scheduled_date')
            scheduled_time_str = request.form.get('scheduled_time')
            end_time_str = request.form.get('end_time')
            notes = request.form.get('notes')
            
            # Parse date and times
            scheduled_date = datetime.strptime(scheduled_date_str, '%Y-%m-%d').date()
            scheduled_time = datetime.strptime(scheduled_time_str, '%H:%M').time()
            end_time = datetime.strptime(end_time_str, '%H:%M').time()
            
            # Validate end time is after start time
            if end_time <= scheduled_time:
                flash('End time must be after start time!', 'error')
                return redirect(url_for('create_game_event'))
            
            # Check for location conflicts
            location_available, conflicting_location_event = check_location_conflict(
                location_id, scheduled_date, scheduled_time, end_time
            )
            
            if not location_available:
                location = Location.query.get(location_id)
                flash(f'Location "{location.name}" is already booked from {conflicting_location_event.scheduled_time.strftime("%H:%M")} to {conflicting_location_event.end_time.strftime("%H:%M")} for {conflicting_location_event.game.name}!', 'error')
                return redirect(url_for('create_game_event'))
            
            # Check for group conflicts
            group_available, conflicting_group_event = check_group_conflict(
                group_id, scheduled_date, scheduled_time, end_time
            )
            
            if not group_available:
                group = Group.query.get(group_id)
                flash(f'Group {group.name} already has "{conflicting_group_event.game.name}" scheduled from {conflicting_group_event.scheduled_time.strftime("%H:%M")} to {conflicting_group_event.end_time.strftime("%H:%M")}!', 'error')
                return redirect(url_for('create_game_event'))
            
            game_event = GameEvent(
                game_id=game_id,
                group_id=group_id,
                location_id=location_id,
                scheduled_date=scheduled_date,
                scheduled_time=scheduled_time,
                end_time=end_time,
                status='Scheduled',
                gender_restriction=gender_restriction,  # NEW
                notes=notes
            )
            
            db.session.add(game_event)
            db.session.commit()
            
            game = Game.query.get(game_id)
            group = Group.query.get(group_id)
            flash(f'Game event "{game.name}" for Group {group.name} ({gender_restriction}) scheduled successfully!', 'success')
            return redirect(url_for('list_game_events'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating game event: {str(e)}', 'error')
            return redirect(url_for('create_game_event'))
    
    # GET request
    games = Game.query.order_by(Game.game_type, Game.name).all()
    groups = Group.query.order_by(Group.standard_from).all()
    locations = Location.query.order_by(Location.name).all()
    
    return render_template('game_events/create.html', games=games, groups=groups, locations=locations)



@app.route('/game-events/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def edit_game_event(id):
    """Edit an existing game event"""
    game_event = GameEvent.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            game_id = int(request.form.get('game_id'))
            group_id = int(request.form.get('group_id'))
            location_id = int(request.form.get('location_id'))
            gender_restriction = request.form.get('gender_restriction')  # NEW
            scheduled_date_str = request.form.get('scheduled_date')
            scheduled_time_str = request.form.get('scheduled_time')
            end_time_str = request.form.get('end_time')
            status = request.form.get('status')
            notes = request.form.get('notes')
            
            # Parse date and times
            scheduled_date = datetime.strptime(scheduled_date_str, '%Y-%m-%d').date()
            scheduled_time = datetime.strptime(scheduled_time_str, '%H:%M').time()
            end_time = datetime.strptime(end_time_str, '%H:%M').time()
            
            # Validate end time is after start time
            if end_time <= scheduled_time:
                flash('End time must be after start time!', 'error')
                return redirect(url_for('edit_game_event', id=id))
            
            # Check for location conflicts (exclude current event)
            location_available, conflicting_location_event = check_location_conflict(
                location_id, scheduled_date, scheduled_time, end_time, exclude_event_id=id
            )
            
            if not location_available:
                location = Location.query.get(location_id)
                flash(f'Location "{location.name}" is already booked from {conflicting_location_event.scheduled_time.strftime("%H:%M")} to {conflicting_location_event.end_time.strftime("%H:%M")} for {conflicting_location_event.game.name}!', 'error')
                return redirect(url_for('edit_game_event', id=id))
            
            # Check for group conflicts (exclude current event)
            group_available, conflicting_group_event = check_group_conflict(
                group_id, scheduled_date, scheduled_time, end_time, exclude_event_id=id
            )
            
            if not group_available:
                group = Group.query.get(group_id)
                flash(f'Group {group.name} already has "{conflicting_group_event.game.name}" scheduled from {conflicting_group_event.scheduled_time.strftime("%H:%M")} to {conflicting_group_event.end_time.strftime("%H:%M")}!', 'error')
                return redirect(url_for('edit_game_event', id=id))
            
            game_event.game_id = game_id
            game_event.group_id = group_id
            game_event.location_id = location_id
            game_event.scheduled_date = scheduled_date
            game_event.scheduled_time = scheduled_time
            game_event.end_time = end_time
            game_event.status = status
            game_event.gender_restriction = gender_restriction  # NEW
            game_event.notes = notes
            
            db.session.commit()
            
            flash('Game event updated successfully!', 'success')
            return redirect(url_for('list_game_events'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating game event: {str(e)}', 'error')
            return redirect(url_for('edit_game_event', id=id))
    
    # GET request
    games = Game.query.order_by(Game.game_type, Game.name).all()
    groups = Group.query.order_by(Group.standard_from).all()
    locations = Location.query.order_by(Location.name).all()
    
    return render_template('game_events/edit.html', game_event=game_event, games=games, groups=groups, locations=locations)


@app.route('/game-events/delete/<int:id>', methods=['POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def delete_game_event(id):
    """Delete a game event and all related participations"""
    try:
        game_event = GameEvent.query.get_or_404(id)
        game_name = game_event.game.name
        group_name = game_event.group.name
        
        # Count participations
        participation_count = Participation.query.filter_by(game_event_id=id).count()
        
        db.session.delete(game_event)
        db.session.commit()
        
        if participation_count > 0:
            flash(f'Game event "{game_name}" for Group {group_name} and {participation_count} participation(s) deleted!', 'warning')
        else:
            flash(f'Game event "{game_name}" for Group {group_name} deleted successfully!', 'success')
        
        return redirect(url_for('list_game_events'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting game event: {str(e)}', 'error')
        return redirect(url_for('list_game_events'))






# ============= GROUPS ROUTES =============

@app.route('/groups')
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def list_groups():
    """List all groups"""
    groups = Group.query.order_by(Group.standard_from).all()
    return render_template('groups/list.html', groups=groups)

@app.route('/groups/create', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def create_group():
    """Create a new group"""
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            standard_from = int(request.form.get('standard_from'))
            standard_to = int(request.form.get('standard_to'))
            description = request.form.get('description')
            
            # Validation
            if standard_from > standard_to:
                flash('Starting standard cannot be greater than ending standard!', 'error')
                return redirect(url_for('create_group'))
            
            if standard_from < 1 or standard_to > 12:
                flash('Standard range must be between 1 and 12!', 'error')
                return redirect(url_for('create_group'))
            
            # Check for overlapping ranges
            is_valid, error_msg = check_standard_range_overlap(standard_from, standard_to)
            if not is_valid:
                flash(error_msg, 'error')
                return redirect(url_for('create_group'))
            
            group = Group(
                name=name,
                standard_from=standard_from,
                standard_to=standard_to,
                description=description
            )
            
            db.session.add(group)
            db.session.commit()
            
            flash(f'Group "{name}" created successfully!', 'success')
            return redirect(url_for('list_groups'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating group: {str(e)}', 'error')
            return redirect(url_for('create_group'))
    
    return render_template('groups/create.html')

@app.route('/groups/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def edit_group(id):
    """Edit an existing group"""
    group = Group.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            standard_from = int(request.form.get('standard_from'))
            standard_to = int(request.form.get('standard_to'))
            description = request.form.get('description')
            
            # Validation
            if standard_from > standard_to:
                flash('Starting standard cannot be greater than ending standard!', 'error')
                return redirect(url_for('edit_group', id=id))
            
            if standard_from < 1 or standard_to > 12:
                flash('Standard range must be between 1 and 12!', 'error')
                return redirect(url_for('edit_group', id=id))
            
            # Check for overlapping ranges (exclude current group)
            is_valid, error_msg = check_standard_range_overlap(standard_from, standard_to, exclude_group_id=id)
            if not is_valid:
                flash(error_msg, 'error')
                return redirect(url_for('edit_group', id=id))
            
            group.name = name
            group.standard_from = standard_from
            group.standard_to = standard_to
            group.description = description
            
            db.session.commit()
            
            flash(f'Group "{name}" updated successfully!', 'success')
            return redirect(url_for('list_groups'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating group: {str(e)}', 'error')
            return redirect(url_for('edit_group', id=id))
    
    return render_template('groups/edit.html', group=group)

@app.route('/groups/delete/<int:id>', methods=['POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def delete_group(id):
    """Delete a group and all related data"""
    try:
        group = Group.query.get_or_404(id)
        group_name = group.name
        
        # Count related data
        student_count = Student.query.filter_by(group_id=id).count()
        event_count = GameEvent.query.filter_by(group_id=id).count()
        
        db.session.delete(group)
        db.session.commit()
        
        warning_parts = []
        if student_count > 0:
            warning_parts.append(f"{student_count} student(s)")
        if event_count > 0:
            warning_parts.append(f"{event_count} event(s)")
        
        if warning_parts:
            flash(f'Group "{group_name}" and {" and ".join(warning_parts)} deleted successfully!', 'warning')
        else:
            flash(f'Group "{group_name}" deleted successfully!', 'success')
        
        return redirect(url_for('list_groups'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting group: {str(e)}', 'error')
        return redirect(url_for('list_groups'))

# ============= SANSKARVARGS ROUTES =============

@app.route('/sanskarvargs')
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def list_sanskarvargs():
    """List all sanskarvargs"""
    sanskarvargs = Sanskarvarg.query.order_by(Sanskarvarg.name).all()
    return render_template('sanskarvargs/list.html', sanskarvargs=sanskarvargs)

@app.route('/sanskarvargs/create', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def create_sanskarvarg():
    """Create a new sanskarvarg"""
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            contact_person_1 = request.form.get('contact_person_1')
            contact_phone_1 = request.form.get('contact_phone_1')
            contact_person_2 = request.form.get('contact_person_2')
            contact_phone_2 = request.form.get('contact_phone_2')
            address = request.form.get('address')
            
            # Generate unique abbreviation
            existing_abbrs = {s.abbreviation for s in Sanskarvarg.query.all()}
            abbreviation = generate_abbreviation(name, existing_abbrs)
            
            sanskarvarg = Sanskarvarg(
                name=name,
                abbreviation=abbreviation,
                contact_person_1=contact_person_1,
                contact_phone_1=contact_phone_1,
                contact_person_2=contact_person_2,
                contact_phone_2=contact_phone_2,
                address=address
            )
            
            db.session.add(sanskarvarg)
            db.session.commit()
            
            # Check if counter already exists first
            existing_counter = StudentCounter.query.filter_by(sanskarvarg_id=sanskarvarg.id).first()
            if not existing_counter:
                # Only create if it doesn't exist
                counter = StudentCounter(sanskarvarg_id=sanskarvarg.id, counter=0)
                db.session.add(counter)
                db.session.commit()
                        
            flash(f'Sanskarvarg "{name}" created with abbreviation "{abbreviation}"!', 'success')
            return redirect(url_for('list_sanskarvargs'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating sanskarvarg: {str(e)}', 'error')
            return redirect(url_for('create_sanskarvarg'))
    
    return render_template('sanskarvargs/create.html')

@app.route('/sanskarvargs/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def edit_sanskarvarg(id):
    """Edit an existing sanskarvarg"""
    sanskarvarg = Sanskarvarg.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            contact_person_1 = request.form.get('contact_person_1')
            contact_phone_1 = request.form.get('contact_phone_1')
            contact_person_2 = request.form.get('contact_person_2')
            contact_phone_2 = request.form.get('contact_phone_2')
            address = request.form.get('address')
            
            # If name changed, regenerate abbreviation
            if name != sanskarvarg.name:
                existing_abbrs = {s.abbreviation for s in Sanskarvarg.query.filter(Sanskarvarg.id != id).all()}
                abbreviation = generate_abbreviation(name, existing_abbrs)
                sanskarvarg.abbreviation = abbreviation
            
            sanskarvarg.name = name
            sanskarvarg.contact_person_1 = contact_person_1
            sanskarvarg.contact_phone_1 = contact_phone_1
            sanskarvarg.contact_person_2 = contact_person_2
            sanskarvarg.contact_phone_2 = contact_phone_2
            sanskarvarg.address = address
            
            db.session.commit()
            
            flash(f'Sanskarvarg "{name}" updated successfully!', 'success')
            return redirect(url_for('list_sanskarvargs'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating sanskarvarg: {str(e)}', 'error')
            return redirect(url_for('edit_sanskarvarg', id=id))
    
    return render_template('sanskarvargs/edit.html', sanskarvarg=sanskarvarg)

@app.route('/sanskarvargs/delete/<int:id>', methods=['POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def delete_sanskarvarg(id):
    """Delete a sanskarvarg and all related data"""
    try:
        sanskarvarg = Sanskarvarg.query.get_or_404(id)
        sanskarvarg_name = sanskarvarg.name
        
        # Count related data
        student_count = Student.query.filter_by(sanskarvarg_id=id).count()
        
        db.session.delete(sanskarvarg)
        db.session.commit()
        
        if student_count > 0:
            flash(f'Sanskarvarg "{sanskarvarg_name}" and {student_count} student(s) deleted successfully!', 'warning')
        else:
            flash(f'Sanskarvarg "{sanskarvarg_name}" deleted successfully!', 'success')
        
        return redirect(url_for('list_sanskarvargs'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting sanskarvarg: {str(e)}', 'error')
        return redirect(url_for('list_sanskarvargs'))

# ============= LOCATIONS ROUTES =============

@app.route('/locations')
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def list_locations():
    """List all locations"""
    locations = Location.query.order_by(Location.name).all()
    return render_template('locations/list.html', locations=locations)

@app.route('/locations/create', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def create_location():
    """Create a new location"""
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            address = request.form.get('address')
            
            location = Location(
                name=name,
                address=address
            )
            
            db.session.add(location)
            db.session.commit()
            
            flash(f'Location "{name}" created successfully!', 'success')
            return redirect(url_for('list_locations'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating location: {str(e)}', 'error')
            return redirect(url_for('create_location'))
    
    return render_template('locations/create.html')

@app.route('/locations/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def edit_location(id):
    """Edit an existing location"""
    location = Location.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            address = request.form.get('address')
            
            location.name = name
            location.address = address
            
            db.session.commit()
            
            flash(f'Location "{name}" updated successfully!', 'success')
            return redirect(url_for('list_locations'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating location: {str(e)}', 'error')
            return redirect(url_for('edit_location', id=id))
    
    return render_template('locations/edit.html', location=location)

@app.route('/locations/delete/<int:id>', methods=['POST'])
@login_required
@role_required('UtsavPramukh', 'Sanchalan')
def delete_location(id):
    """Delete a location and all related data"""
    try:
        location = Location.query.get_or_404(id)
        location_name = location.name
        
        # Count related data
        event_count = GameEvent.query.filter_by(location_id=id).count()
        
        db.session.delete(location)
        db.session.commit()
        
        if event_count > 0:
            flash(f'Location "{location_name}" and {event_count} event(s) deleted successfully!', 'warning')
        else:
            flash(f'Location "{location_name}" deleted successfully!', 'success')
        
        return redirect(url_for('list_locations'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting location: {str(e)}', 'error')
        return redirect(url_for('list_locations'))





# ============= STUDENTS ROUTES =============

@app.route('/students')
@login_required
@role_required('UtsavPramukh', 'Vargshikshak')  # CHANGE ORDER
def list_students():
    """List all students"""
    current_user = get_current_user()
    
    if current_user.is_vargshikshak():
        # Only show students from assigned sanskarvargs
        assigned_ids = current_user.get_assigned_sanskarvarg_ids()
        students = Student.query.filter(
            Student.sanskarvarg_id.in_(assigned_ids)
        ).order_by(Student.created_at.desc()).all()
    else:
        # UtsavPramukh can see all
        students = Student.query.order_by(Student.created_at.desc()).all()
    
    return render_template('students/list.html', students=students)

@app.route('/students/register', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh', 'Vargshikshak')
def register_students():
    """Student registration form"""
    if request.method == 'POST':
        try:
            data = request.get_json()
            sanskarvarg_id = int(data.get('sanskarvarg_id'))
            group_id = int(data.get('group_id'))
            students_data = data.get('students', [])
            
            if not students_data:
                return jsonify({'success': False, 'message': 'No students to register'}), 400
            
            # Get group to validate standards
            group = Group.query.get_or_404(group_id)
            sanskarvarg = Sanskarvarg.query.get_or_404(sanskarvarg_id)
            
            registered_students = []
            
            for student_data in students_data:
                name = student_data['name']
                gender = student_data['gender']
                standard = int(student_data['standard'])
                dob_str = student_data['dob']
                games = student_data.get('games', [])
                
                # Validate standard is within group range
                if standard < group.standard_from or standard > group.standard_to:
                    return jsonify({
                        'success': False,
                        'message': f'Student "{name}" has standard {standard} which is not in Group {group.name} range (Std {group.standard_from}-{group.standard_to})'
                    }), 400
                
                # Parse date
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
                
                # Generate student ID
                student_id = generate_student_id(sanskarvarg_id, dob)
                
                # Create student
                student = Student(
                    student_id=student_id,
                    name=name,
                    gender=gender,
                    date_of_birth=dob,
                    standard=standard,
                    sanskarvarg_id=sanskarvarg_id,
                    group_id=group_id
                )
                db.session.add(student)
                db.session.flush()
                
                # Register for games
                for game_data in games:
                    game_event_id = game_data['game_event_id']
                    team_name = game_data.get('team_name')
                    
                    participation = Participation(
                        student_id=student.id,
                        game_event_id=game_event_id,
                        team_name=team_name
                    )
                    db.session.add(participation)
                
                registered_students.append({
                    'student_id': student_id,
                    'name': name
                })
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'{len(registered_students)} student(s) registered successfully!',
                'students': registered_students
            })
            
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500
    
    # GET request
    sanskarvargs = Sanskarvarg.query.order_by(Sanskarvarg.name).all()
    groups = Group.query.order_by(Group.standard_from).all()
    return render_template('students/register.html', sanskarvargs=sanskarvargs, groups=groups)

def generate_student_id(sanskarvarg_id, date_of_birth):
    """Generate unique student ID: XXX-DDMMYYYY-NNN"""
    sanskarvarg = Sanskarvarg.query.get(sanskarvarg_id)
    counter_obj = StudentCounter.query.get(sanskarvarg_id)
    
    if not counter_obj:
        counter_obj = StudentCounter(sanskarvarg_id=sanskarvarg_id, counter=0)
        db.session.add(counter_obj)
    
    counter_obj.counter += 1
    db.session.flush()
    
    abbreviation = sanskarvarg.abbreviation.upper()
    dob_str = date_of_birth.strftime('%d%m%Y')
    counter_str = str(counter_obj.counter).zfill(3)
    
    return f"{abbreviation}-{dob_str}-{counter_str}"


def check_location_conflict(location_id, scheduled_date, scheduled_time, end_time, exclude_event_id=None):
    """
    Check if location is available during the specified time range.
    Returns (is_available, conflicting_event)
    """
    query = GameEvent.query.filter(
        GameEvent.location_id == location_id,
        GameEvent.scheduled_date == scheduled_date,
        GameEvent.status != 'Cancelled'
    )
    
    if exclude_event_id:
        query = query.filter(GameEvent.id != exclude_event_id)
    
    existing_events = query.all()
    
    for event in existing_events:
        # Check for time overlap
        if not (end_time <= event.scheduled_time or scheduled_time >= event.end_time):
            return False, event
    
    return True, None


def check_group_conflict(group_id, scheduled_date, scheduled_time, end_time, exclude_event_id=None):
    """
    Check if group has any conflicting events at the specified time.
    Returns (is_available, conflicting_event)
    """
    query = GameEvent.query.filter(
        GameEvent.group_id == group_id,
        GameEvent.scheduled_date == scheduled_date,
        GameEvent.status != 'Cancelled'
    )
    
    if exclude_event_id:
        query = query.filter(GameEvent.id != exclude_event_id)
    
    existing_events = query.all()
    
    for event in existing_events:
        # Check for time overlap
        if not (end_time <= event.scheduled_time or scheduled_time >= event.end_time):
            return False, event
    
    return True, None





# Replace your /api/games-for-group route in app.py with this

@app.route('/api/games-for-group/<int:group_id>')

def api_games_for_group(group_id):
    """Get all games that have events scheduled for a specific group"""
    try:
        # Get all game events for this group
        game_events = GameEvent.query.filter_by(group_id=group_id).all()
        
        if not game_events:
            return jsonify([])
        
        # Get unique games and their events
        games_dict = {}
        for event in game_events:
            game = event.game
            if game.id not in games_dict:
                games_dict[game.id] = {
                    'id': game.id,
                    'name': game.name,
                    'game_type': game.game_type,
                    'is_team': game.is_team_game(),
                    'min_team_size': game.min_team_size,
                    'max_team_size': game.max_team_size,
                    'capacity_per_round': game.capacity_per_round,
                    'events': []
                }
            
            games_dict[game.id]['events'].append({
                'id': event.id,
                'location': event.location.name,
                'date': event.scheduled_date.strftime('%Y-%m-%d'),
                'time': event.scheduled_time.strftime('%H:%M'),
                'gender_restriction': event.gender_restriction  # NEW - IMPORTANT!
            })
        
        # Convert to list and sort by game type and name
        games_list = list(games_dict.values())
        games_list.sort(key=lambda x: (x['game_type'], x['name']))
        
        return jsonify(games_list)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@app.route('/api/group-info/<int:group_id>')

def api_group_info(group_id):
    """Get group information including standard range"""
    try:
        group = Group.query.get_or_404(group_id)
        return jsonify({
            'id': group.id,
            'name': group.name,
            'standard_from': group.standard_from,
            'standard_to': group.standard_to,
            'description': group.description
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 404




@app.route('/api/students-by-group')
@login_required  # Already has this
def api_students_by_group():
    """Get all students for a specific sanskarvarg and group"""
    current_user = get_current_user()
    
    try:
        sanskarvarg_id = request.args.get('sanskarvarg_id', type=int)
        group_id = request.args.get('group_id', type=int)
        
        if not sanskarvarg_id or not group_id:
            return jsonify([])
        
        # CHECK PERMISSION FOR VARGSHIKSHAK - ADD THIS BLOCK
        if current_user.is_vargshikshak():
            assigned_ids = current_user.get_assigned_sanskarvarg_ids()
            if sanskarvarg_id not in assigned_ids:
                return jsonify({'error': 'Permission denied'}), 403
        
        # Rest of existing code...
        students = Student.query.filter_by(
            sanskarvarg_id=sanskarvarg_id,
            group_id=group_id
        ).all()
        
        result = []
        for student in students:
            participations = []
            for p in student.participations:
                participations.append({
                    'game_event_id': p.game_event_id,
                    'team_name': p.team_name
                })
            
            result.append({
                'id': student.id,
                'student_id': student.student_id,
                'name': student.name,
                'gender': student.gender,
                'standard': student.standard,
                'date_of_birth': student.date_of_birth.strftime('%Y-%m-%d'),
                'participations': participations
            })
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============= NEW ROUTE: Save/Update Students =============

@app.route('/students/save', methods=['POST'])
@login_required
@role_required('UtsavPramukh', 'Vargshikshak')  # CHANGE ORDER
def save_students():
    """Save both new and existing students with their game participations"""
    current_user = get_current_user()
    
    try:
        data = request.get_json()
        sanskarvarg_id = int(data.get('sanskarvarg_id'))
        group_id = int(data.get('group_id'))
        students_to_update = data.get('students_to_update', [])
        students_to_create = data.get('students_to_create', [])
        is_final_submit = data.get('is_final_submit', False)
        
        # CHECK PERMISSION FOR VARGSHIKSHAK - ADD THIS BLOCK
        if current_user.is_vargshikshak():
            assigned_ids = current_user.get_assigned_sanskarvarg_ids()
            if sanskarvarg_id not in assigned_ids:
                return jsonify({
                    'success': False,
                    'message': 'You do not have permission to register students for this Sanskarvarg'
                }), 403
            
        updated_count = 0
        created_count = 0
        created_students = []
        
        # If final submit, validate team sizes
        if is_final_submit:
            validation_result = validate_team_sizes(sanskarvarg_id, group_id, students_to_update + students_to_create)
            if not validation_result['valid']:
                return jsonify({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': validation_result['errors']
                }), 400
        
        # Update existing students
        for student_data in students_to_update:
            student_id = student_data['id']
            student = Student.query.get(student_id)
            
            if not student:
                continue
            
            # Update basic info
            student.name = student_data['name']
            student.gender = student_data['gender']
            student.standard = int(student_data['standard'])
            student.date_of_birth = datetime.strptime(student_data['dob'], '%Y-%m-%d').date()
            
            # Update participations
            Participation.query.filter_by(student_id=student.id).delete()
            
            for game_data in student_data.get('games', []):
                participation = Participation(
                    student_id=student.id,
                    game_event_id=game_data['game_event_id'],
                    team_name=game_data.get('team_name')
                )
                db.session.add(participation)
            
            updated_count += 1
        
        # Create new students
        for student_data in students_to_create:
            name = student_data['name']
            gender = student_data['gender']
            standard = int(student_data['standard'])
            dob = datetime.strptime(student_data['dob'], '%Y-%m-%d').date()
            games = student_data.get('games', [])
            
            student_id = generate_student_id(sanskarvarg_id, dob)
            
            student = Student(
                student_id=student_id,
                name=name,
                gender=gender,
                date_of_birth=dob,
                standard=standard,
                sanskarvarg_id=sanskarvarg_id,
                group_id=group_id
            )
            db.session.add(student)
            db.session.flush()
            
            for game_data in games:
                participation = Participation(
                    student_id=student.id,
                    game_event_id=game_data['game_event_id'],
                    team_name=game_data.get('team_name')
                )
                db.session.add(participation)
            
            created_students.append({
                'student_id': student_id,
                'name': name
            })
            created_count += 1
        
        # If final submit, mark as submitted
        if is_final_submit:
            submission = SubmissionStatus.query.filter_by(
                sanskarvarg_id=sanskarvarg_id,
                group_id=group_id
            ).first()
            
            if not submission:
                submission = SubmissionStatus(
                    sanskarvarg_id=sanskarvarg_id,
                    group_id=group_id
                )
                db.session.add(submission)
            
            submission.is_submitted = True
            submission.submitted_at = datetime.utcnow()
        
        db.session.commit()
        
        messages = []
        if updated_count > 0:
            messages.append(f'{updated_count} student(s) updated')
        if created_count > 0:
            messages.append(f'{created_count} new student(s) created')
        
        message = ' and '.join(messages) if messages else 'No changes'
        if is_final_submit:
            message += '. Registration submitted and locked!'
        else:
            message += ' successfully!'
        
        return jsonify({
            'success': True,
            'message': message,
            'created_students': created_students,
            'updated_count': updated_count,
            'created_count': created_count,
            'is_submitted': is_final_submit
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

# ============= SUBMISSION STATUS ROUTES =============

@app.route('/submissions')
@login_required
@role_required('UtsavPramukh')
def list_submissions():
    """List all submissions with their status"""
    
    # FIX: MySQL doesn't support .nullsfirst(). 
    # In MySQL, DESC naturally puts NULLs last. 
    # To force NULLs to the top, we sort by the boolean check first.
    submissions_query = SubmissionStatus.query.order_by(
        SubmissionStatus.submitted_at.is_(None).desc(), # True (1) for NULLs comes before False (0)
        SubmissionStatus.submitted_at.desc()
    ).all()
    
    # Optimized approach: Get all data in fewer queries
    all_combinations = []
    sanskarvargs = Sanskarvarg.query.all()
    groups = Group.query.all()
    
    for sanskarvarg in sanskarvargs:
        for group in groups:
            # Count students for this specific combination
            student_count = Student.query.filter_by(
                sanskarvarg_id=sanskarvarg.id,
                group_id=group.id
            ).count()
            
            if student_count > 0:
                # Find the matching submission from our pre-fetched list 
                # or query it specifically if the list is too large
                submission = SubmissionStatus.query.filter_by(
                    sanskarvarg_id=sanskarvarg.id,
                    group_id=group.id
                ).first()
                
                all_combinations.append({
                    'sanskarvarg': sanskarvarg,
                    'group': group,
                    'student_count': student_count,
                    'submission': submission
                })
    
    return render_template('submissions/list.html', combinations=all_combinations)


@app.route('/submissions/unlock/<int:submission_id>', methods=['POST'])
@login_required
@role_required('UtsavPramukh')
def unlock_submission(submission_id):
    """Unlock a submission for editing"""
    try:
        submission = SubmissionStatus.query.get_or_404(submission_id)
        submission.is_submitted = False
        submission.submitted_at = None
        
        db.session.commit()
        
        flash(f'Submission for {submission.sanskarvarg.name} - Group {submission.group.name} unlocked successfully!', 'success')
        return redirect(url_for('list_submissions'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error unlocking submission: {str(e)}', 'error')
        return redirect(url_for('list_submissions'))


@app.route('/api/submission-status/<int:sanskarvarg_id>/<int:group_id>')
@login_required  # Already has this
def api_submission_status(sanskarvarg_id, group_id):
    """Get submission status for a sanskarvarg-group combination"""
    current_user = get_current_user()
    
    try:
        # CHECK PERMISSION FOR VARGSHIKSHAK - ADD THIS BLOCK
        if current_user.is_vargshikshak():
            assigned_ids = current_user.get_assigned_sanskarvarg_ids()
            if sanskarvarg_id not in assigned_ids:
                return jsonify({'error': 'Permission denied'}), 403
        
        submission = SubmissionStatus.query.filter_by(
            sanskarvarg_id=sanskarvarg_id,
            group_id=group_id
        ).first()
        
        return jsonify({
            'is_submitted': submission.is_submitted if submission else False,
            'submitted_at': submission.submitted_at.isoformat() if submission and submission.submitted_at else None
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/submissions/view/<int:sanskarvarg_id>/<int:group_id>')
@login_required
@role_required('UtsavPramukh')
def view_submission(sanskarvarg_id, group_id):
    """View a specific submission (read-only unless unlocked)"""
    try:
        # Get sanskarvarg and group
        sanskarvarg = Sanskarvarg.query.get_or_404(sanskarvarg_id)
        group = Group.query.get_or_404(group_id)
        
        # Get submission status
        submission = SubmissionStatus.query.filter_by(
            sanskarvarg_id=sanskarvarg_id,
            group_id=group_id
        ).first()
        
        # Get all students for this combination
        students = Student.query.filter_by(
            sanskarvarg_id=sanskarvarg_id,
            group_id=group_id
        ).all()
        
        # Get games for this group
        game_events = GameEvent.query.filter_by(group_id=group_id).all()
        
        # Organize games by type
        games_by_type = {
            'Individual': [],
            'Team': [],
            'Baudhik': []
        }
        
        for event in game_events:
            game = event.game
            if game.game_type not in games_by_type:
                games_by_type[game.game_type] = []
            
            # Avoid duplicates
            if not any(g['id'] == game.id for g in games_by_type[game.game_type]):
                games_by_type[game.game_type].append({
                    'id': game.id,
                    'name': game.name,
                    'game_type': game.game_type,
                    'is_team': game.is_team_game(),
                    'event_id': event.id
                })
        
        # Prepare student data with participations
        student_data = []
        for student in students:
            participations = {}
            for p in student.participations:
                game_id = p.game_event.game_id
                participations[game_id] = {
                    'participating': True,
                    'team_name': p.team_name
                }
            
            student_data.append({
                'id': student.id,
                'student_id': student.student_id,
                'name': student.name,
                'gender': student.gender,
                'standard': student.standard,
                'date_of_birth': student.date_of_birth,
                'participations': participations
            })
        
        return render_template(
            'submissions/view.html',
            sanskarvarg=sanskarvarg,
            group=group,
            submission=submission,
            students=student_data,
            games_by_type=games_by_type,
            is_submitted=submission.is_submitted if submission else False
        )
        
    except Exception as e:
        flash(f'Error loading submission: {str(e)}', 'error')
        return redirect(url_for('list_submissions'))

@app.route('/students/delete/<int:student_id>', methods=['POST'])
@login_required
@role_required('UtsavPramukh', 'Vargshikshak')
def delete_student(student_id):
    """Delete student - with permission check"""
    current_user = get_current_user()
    
    try:
        student = Student.query.get_or_404(student_id)
        
        # CHECK PERMISSION FOR VARGSHIKSHAK - ADD THIS BLOCK
        if current_user.is_vargshikshak():
            assigned_ids = current_user.get_assigned_sanskarvarg_ids()
            if student.sanskarvarg_id not in assigned_ids:
                return jsonify({
                    'success': False,
                    'message': 'You do not have permission to delete this student'
                }), 403
        
        # Delete participations first
        Participation.query.filter_by(student_id=student_id).delete()
        
        db.session.delete(student)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Student {student.name} deleted successfully'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False, 
            'message': str(e)
        }), 500




# Add these functions and routes to app.py

def distribute_students_to_rounds_by_sanskarvarg(participations, capacity_per_round):
    """
    Distribute students into rounds prioritizing:
    1. Even distribution across rounds
    2. Keeping students from same sanskarvarg together
    
    Returns: dict mapping participation.id -> round_number
    """
    # Group participations by sanskarvarg
    by_sanskarvarg = {}
    for p in participations:
        svid = p.student.sanskarvarg_id
        if svid not in by_sanskarvarg:
            by_sanskarvarg[svid] = []
        by_sanskarvarg[svid].append(p)
    
    # Calculate total students and number of rounds needed
    total_students = len(participations)
    if total_students == 0:
        return {}
    
    num_rounds = (total_students + capacity_per_round - 1) // capacity_per_round
    
    # Calculate target size per round (as even as possible)
    base_size = total_students // num_rounds
    extra_students = total_students % num_rounds
    
    # Create target sizes for each round
    round_targets = []
    for i in range(num_rounds):
        if i < extra_students:
            round_targets.append(base_size + 1)
        else:
            round_targets.append(base_size)
    
    # Assign rounds
    assignments = {}  # participation.id -> round_number
    current_round = 0
    current_round_count = 0
    
    # Sort sanskarvargs by student count (largest first for better distribution)
    sorted_sanskarvargs = sorted(by_sanskarvarg.items(), key=lambda x: len(x[1]), reverse=True)
    
    for svid, sv_participations in sorted_sanskarvargs:
        sv_size = len(sv_participations)
        
        # Try to fit this sanskarvarg into current round
        while sv_size > 0:
            space_in_current = round_targets[current_round] - current_round_count
            
            if space_in_current >= sv_size:
                # Entire sanskarvarg fits in current round
                for p in sv_participations:
                    assignments[p.id] = current_round + 1  # Rounds are 1-indexed
                current_round_count += sv_size
                sv_size = 0
            elif space_in_current > 0:
                # Partial fit - fill current round and continue to next
                for i in range(space_in_current):
                    assignments[sv_participations[i].id] = current_round + 1
                sv_participations = sv_participations[space_in_current:]
                sv_size -= space_in_current
                current_round_count = round_targets[current_round]
            
            # Move to next round if current is full
            if current_round_count >= round_targets[current_round]:
                current_round += 1
                current_round_count = 0
                
                if current_round >= num_rounds:
                    # Safety check
                    break
    
    return assignments


# ============= GAME EVENT REPORT ROUTES =============

@app.route('/game-events/<int:event_id>/generate-report', methods=['POST'])
@login_required
@role_required('UtsavPramukh')
def generate_report(event_id):
    """Generate and assign rounds for a game event"""
    try:
        event = GameEvent.query.get_or_404(event_id)
        game = event.game
        
        # Get only SUBMITTED registrations
        submitted_students = db.session.query(Student).join(
            SubmissionStatus,
            db.and_(
                Student.sanskarvarg_id == SubmissionStatus.sanskarvarg_id,
                Student.group_id == SubmissionStatus.group_id,
                SubmissionStatus.is_submitted == True
            )
        ).filter(Student.group_id == event.group_id).all()
        
        submitted_student_ids = {s.id for s in submitted_students}
        
        # Get participations for this event (only from submitted registrations)
        participations = Participation.query.filter_by(
            game_event_id=event_id
        ).filter(
            Participation.student_id.in_(submitted_student_ids)
        ).all()
        
        if not participations:
            flash('No students with submitted registrations for this event!', 'warning')
            return redirect(url_for('list_game_events'))
        
        # Assign rounds based on game type
        if game.game_type == 'Individual':
            # Distribute into rounds
            assignments = distribute_students_to_rounds_by_sanskarvarg(
                participations, 
                game.capacity_per_round
            )
            
            # Save assignments
            for p in participations:
                if p.id in assignments:
                    p.round_number = assignments[p.id]
            
        elif game.game_type == 'Baudhik':
            if game.capacity_per_round:
                # Limited capacity - distribute like individual
                assignments = distribute_students_to_rounds_by_sanskarvarg(
                    participations,
                    game.capacity_per_round
                )
                for p in participations:
                    if p.id in assignments:
                        p.round_number = assignments[p.id]
            else:
                # All in one round
                for p in participations:
                    p.round_number = 1
        
        # Team games don't need round assignment
        
        db.session.commit()
        
        flash(f'Report generated successfully for {game.name}!', 'success')
        return redirect(url_for('view_report', event_id=event_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error generating report: {str(e)}', 'error')
        return redirect(url_for('list_game_events'))


@app.route('/game-events/<int:event_id>/report')
@login_required
@role_required('UtsavPramukh')
def view_report(event_id):
    """View the generated report for a game event"""
    try:
        event = GameEvent.query.get_or_404(event_id)
        game = event.game
        
        # Get only SUBMITTED registrations
        submitted_students = db.session.query(Student).join(
            SubmissionStatus,
            db.and_(
                Student.sanskarvarg_id == SubmissionStatus.sanskarvarg_id,
                Student.group_id == SubmissionStatus.group_id,
                SubmissionStatus.is_submitted == True
            )
        ).filter(Student.group_id == event.group_id).all()
        
        submitted_student_ids = {s.id for s in submitted_students}
        
        # Get participations (only submitted)
        participations = Participation.query.filter_by(
            game_event_id=event_id
        ).filter(
            Participation.student_id.in_(submitted_student_ids)
        ).all()
        
        if not participations:
            return render_template(
                'game_events/report.html',
                event=event,
                game=game,
                has_data=False
            )
        
        # Organize data based on game type
        report_data = None
        
        if game.game_type == 'Team':
            # Group by team name
            teams = {}
            for p in participations:
                team = p.team_name or 'Unassigned'
                if team not in teams:
                    teams[team] = []
                teams[team].append({
                    'student': p.student,
                    'participation_id': p.id
                })
            report_data = {'teams': teams}
            
        elif game.game_type in ['Individual', 'Baudhik']:
            # Group by round number
            rounds = {}
            for p in participations:
                round_num = p.round_number or 0
                if round_num not in rounds:
                    rounds[round_num] = []
                rounds[round_num].append({
                    'student': p.student,
                    'participation_id': p.id
                })
            
            # Sort rounds
            sorted_rounds = sorted(rounds.items())
            report_data = {'rounds': sorted_rounds}
        
        return render_template(
            'game_events/report.html',
            event=event,
            game=game,
            report_data=report_data,
            has_data=True
        )
        
    except Exception as e:
        flash(f'Error loading report: {str(e)}', 'error')
        return redirect(url_for('list_game_events'))


@app.route('/game-events/move-student', methods=['POST'])
@login_required
@role_required('UtsavPramukh')
def move_student():
    """Move a student to a different round"""
    try:
        data = request.get_json()
        participation_id = int(data.get('participation_id'))
        new_round = int(data.get('new_round'))
        
        participation = Participation.query.get_or_404(participation_id)
        participation.round_number = new_round
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Student moved to Round {new_round}'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/game-events/<int:event_id>/export-pdf')
@login_required
@role_required('UtsavPramukh')
def export_report_pdf(event_id):
    """Export report as PDF"""
    try:
        # For now, we'll create a simple implementation
        # You can enhance this with a proper PDF library like ReportLab or WeasyPrint
        
        event = GameEvent.query.get_or_404(event_id)
        game = event.game
        
        # Get data (same as view_report)
        submitted_students = db.session.query(Student).join(
            SubmissionStatus,
            db.and_(
                Student.sanskarvarg_id == SubmissionStatus.sanskarvarg_id,
                Student.group_id == SubmissionStatus.group_id,
                SubmissionStatus.is_submitted == True
            )
        ).filter(Student.group_id == event.group_id).all()
        
        submitted_student_ids = {s.id for s in submitted_students}
        
        participations = Participation.query.filter_by(
            game_event_id=event_id
        ).filter(
            Participation.student_id.in_(submitted_student_ids)
        ).all()
        
        # For now, render a print-friendly HTML page
        # User can use browser's Print to PDF feature
        
        if game.game_type == 'Team':
            teams = {}
            for p in participations:
                team = p.team_name or 'Unassigned'
                if team not in teams:
                    teams[team] = []
                teams[team].append(p.student)
            report_data = {'teams': teams}
            
        elif game.game_type in ['Individual', 'Baudhik']:
            rounds = {}
            for p in participations:
                round_num = p.round_number or 0
                if round_num not in rounds:
                    rounds[round_num] = []
                rounds[round_num].append(p.student)
            sorted_rounds = sorted(rounds.items())
            report_data = {'rounds': sorted_rounds}
        
        return render_template(
            'game_events/report_pdf.html',
            event=event,
            game=game,
            report_data=report_data
        )
        
    except Exception as e:
        flash(f'Error exporting PDF: {str(e)}', 'error')
        return redirect(url_for('view_report', event_id=event_id))








# ============= RESULTS & SCORING ROUTES =============

@app.route('/game-events/<int:event_id>/record-results', methods=['GET', 'POST'])
@login_required
@role_required('UtsavPramukh')
def record_results(event_id):
    """Record 1st, 2nd, 3rd positions for a game event"""
    event = GameEvent.query.get_or_404(event_id)
    game = event.game
    
    if request.method == 'POST':
        try:
            data = request.get_json()
            
            # Delete existing results for this event
            EventResult.query.filter_by(game_event_id=event_id).delete()
            
            # Process each position (1st, 2nd, 3rd)
            for position in [1, 2, 3]:
                position_key = f'position_{position}'
                selected_id = data.get(position_key)
                
                if not selected_id:
                    continue  # Skip if position not filled
                
                if game.is_team_game():
                    # For team games: selected_id is "sanskarvarg_id:team_name"
                    sanskarvarg_id, team_name = selected_id.split(':')
                    result = EventResult(
                        game_event_id=event_id,
                        position=position,
                        sanskarvarg_id=int(sanskarvarg_id),
                        team_name=team_name
                    )
                else:
                    # For individual/baudhik games: selected_id is student_id
                    result = EventResult(
                        game_event_id=event_id,
                        position=position,
                        student_id=int(selected_id)
                    )
                
                db.session.add(result)
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Results recorded successfully!'
            })
            
        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False,
                'message': f'Error: {str(e)}'
            }), 500
    
    # GET request - show form
    # Get submitted students for this group
    submitted_students = db.session.query(Student).join(
        SubmissionStatus,
        db.and_(
            Student.sanskarvarg_id == SubmissionStatus.sanskarvarg_id,
            Student.group_id == SubmissionStatus.group_id,
            SubmissionStatus.is_submitted == True
        )
    ).filter(Student.group_id == event.group_id).all()
    
    submitted_student_ids = {s.id for s in submitted_students}
    
    # Get participants for this event
    participations = Participation.query.filter_by(
        game_event_id=event_id
    ).filter(
        Participation.student_id.in_(submitted_student_ids)
    ).all()
    
    # Prepare options based on game type
    options = []
    
    if game.is_team_game():
        # Group by sanskarvarg and team
        teams = {}
        for p in participations:
            team_key = f"{p.student.sanskarvarg_id}:{p.team_name}"
            if team_key not in teams:
                teams[team_key] = {
                    'id': team_key,
                    'display': f"{p.student.sanskarvarg.name} - {p.team_name}",
                    'sanskarvarg': p.student.sanskarvarg.name,
                    'team': p.team_name
                }
        options = sorted(teams.values(), key=lambda x: x['display'])
    else:
        # Individual/Baudhik - list all participating students
        for p in participations:
            options.append({
                'id': p.student.id,
                'display': f"{p.student.name} ({p.student.sanskarvarg.abbreviation})",
                'student_id': p.student.student_id,
                'name': p.student.name
            })
        options = sorted(options, key=lambda x: x['display'])
    
    # Get existing results if any
    existing_results = EventResult.query.filter_by(game_event_id=event_id).all()
    current_results = {}
    for result in existing_results:
        if game.is_team_game():
            current_results[result.position] = f"{result.sanskarvarg_id}:{result.team_name}"
        else:
            current_results[result.position] = result.student_id
    
    return render_template(
        'results/record_results.html',
        event=event,
        game=game,
        options=options,
        current_results=current_results,
        is_team_game=game.is_team_game()
    )


@app.route('/results/student-leaderboard')
@login_required
@role_required('UtsavPramukh')
def student_leaderboard():
    """Display student-wise points leaderboard"""
    
    # Get all students with their points
    students_points = []
    
    # Get all students
    students = Student.query.all()
    
    for student in students:
        total_points = 0
        
        # Individual/Baudhik game results
        for result in student.individual_results:
            total_points += result.get_points()
        
        # Team game results
        for participation in student.participations:
            if participation.game_event.game.is_team_game():
                # Check if this student's team won
                team_results = EventResult.query.filter_by(
                    game_event_id=participation.game_event_id,
                    sanskarvarg_id=student.sanskarvarg_id,
                    team_name=participation.team_name
                ).all()
                
                for result in team_results:
                    total_points += result.get_points()
        
        if total_points > 0:  # Only include students with points
            students_points.append({
                'student': student,
                'total_points': total_points
            })
    
    # Sort by points (descending)
    students_points.sort(key=lambda x: x['total_points'], reverse=True)
    
    # Assign ranks with tie handling
    current_rank = 1
    for i, item in enumerate(students_points):
        if i > 0 and item['total_points'] < students_points[i-1]['total_points']:
            current_rank += 1
        item['rank'] = current_rank
    
    return render_template(
        'results/student_leaderboard.html',
        students_points=students_points
    )


@app.route('/results/event-wise')
@login_required
@role_required('UtsavPramukh')
def event_wise_results():
    """Display event-wise results (1st, 2nd, 3rd for each event)"""
    
    # Get all game events with results
    events_with_results = []
    
    game_events = GameEvent.query.order_by(
        GameEvent.scheduled_date,
        GameEvent.scheduled_time
    ).all()
    
    for event in game_events:
        results = EventResult.query.filter_by(
            game_event_id=event.id
        ).order_by(EventResult.position).all()
        
        if results:  # Only include events with recorded results
            positions = {}
            for result in results:
                positions[result.position] = result
            
            events_with_results.append({
                'event': event,
                'first': positions.get(1),
                'second': positions.get(2),
                'third': positions.get(3)
            })
    
    return render_template(
        'results/event_wise.html',
        events_with_results=events_with_results
    )


@app.route('/results/export-combined-pdf')
@login_required
@role_required('UtsavPramukh')
def export_combined_results():
    """Export both leaderboard and event-wise results as printable PDF"""
    
    # Get student leaderboard data
    students_points = []
    students = Student.query.all()
    
    for student in students:
        total_points = 0
        
        for result in student.individual_results:
            total_points += result.get_points()
        
        for participation in student.participations:
            if participation.game_event.game.is_team_game():
                team_results = EventResult.query.filter_by(
                    game_event_id=participation.game_event_id,
                    sanskarvarg_id=student.sanskarvarg_id,
                    team_name=participation.team_name
                ).all()
                
                for result in team_results:
                    total_points += result.get_points()
        
        if total_points > 0:
            students_points.append({
                'student': student,
                'total_points': total_points
            })
    
    students_points.sort(key=lambda x: x['total_points'], reverse=True)
    
    # Assign ranks with tie handling
    current_rank = 1
    for i, item in enumerate(students_points):
        if i > 0 and item['total_points'] < students_points[i-1]['total_points']:
            current_rank = i + 1
        item['rank'] = current_rank
    
    # Get event-wise results
    events_with_results = []
    game_events = GameEvent.query.order_by(
        GameEvent.scheduled_date,
        GameEvent.scheduled_time
    ).all()
    
    for event in game_events:
        results = EventResult.query.filter_by(
            game_event_id=event.id
        ).order_by(EventResult.position).all()
        
        if results:
            positions = {}
            for result in results:
                positions[result.position] = result
            
            events_with_results.append({
                'event': event,
                'first': positions.get(1),
                'second': positions.get(2),
                'third': positions.get(3)
            })
    
    return render_template(
        'results/combined_pdf.html',
        students_points=students_points,
        events_with_results=events_with_results,
        current_date=datetime.now().strftime('%d %B %Y at %I:%M %p')
    )



# Add these routes to app.py

@app.route('/generate-slips')
@login_required
@role_required('UtsavPramukh')
def generate_slips_page():
    """Page to select sanskarvarg for generating schedule slips"""
    sanskarvargs = Sanskarvarg.query.order_by(Sanskarvarg.name).all()
    return render_template('slips/generate.html', sanskarvargs=sanskarvargs)


@app.route('/generate-slips/<int:sanskarvarg_id>')
@login_required
@role_required('UtsavPramukh')
def generate_slips_pdf(sanskarvarg_id):
    """Generate schedule slips PDF for a sanskarvarg"""
    try:
        sanskarvarg = Sanskarvarg.query.get_or_404(sanskarvarg_id)
        
        # Get all students from this sanskarvarg with SUBMITTED registrations
        submitted_students = db.session.query(Student).join(
            SubmissionStatus,
            db.and_(
                Student.sanskarvarg_id == SubmissionStatus.sanskarvarg_id,
                Student.group_id == SubmissionStatus.group_id,
                SubmissionStatus.is_submitted == True
            )
        ).filter(Student.sanskarvarg_id == sanskarvarg_id).all()
        
        # Prepare slip data for each student
        slips_data = []
        
        for student in submitted_students:
            # Get all participations for this student
            participations = Participation.query.filter_by(
                student_id=student.id
            ).all()
            
            # Build schedule entries
            schedule = []
            for p in participations:
                event = p.game_event
                game = event.game
                
                # Format event name with round/team info
                event_name = game.name
                if game.game_type == 'Team' and p.team_name:
                    event_name += f" ({p.team_name})"
                elif game.game_type == 'Individual' and p.round_number:
                    event_name += f" (Rd {p.round_number})"
                elif game.game_type == 'Baudhik' and p.round_number:
                    event_name += f" (Rd {p.round_number})"
                
                schedule.append({
                    'date': event.scheduled_date,
                    'start_time': event.scheduled_time,
                    'end_time': event.end_time,
                    'event_name': event_name,
                    'location': event.location.name,
                    # For sorting
                    'datetime': datetime.combine(event.scheduled_date, event.scheduled_time)
                })
            
            # Sort schedule by date and time
            schedule.sort(key=lambda x: x['datetime'])
            
            slips_data.append({
                'student': student,
                'schedule': schedule
            })
        
        # Sort slips by student name for easier distribution
        slips_data.sort(key=lambda x: x['student'].name)
        
        return render_template(
            'slips/pdf.html',
            sanskarvarg=sanskarvarg,
            slips_data=slips_data
        )
        
    except Exception as e:
        flash(f'Error generating slips: {str(e)}', 'error')
        return redirect(url_for('generate_slips_page'))





if __name__ == '__main__':
    app.run(debug=True, port=5050, host='0.0.0.0')