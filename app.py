from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, date, timedelta
import calendar
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from werkzeug.utils import secure_filename # For secure filenames
import secrets # For random hex for filenames

# Initialize the Flask application
app = Flask(__name__)

# Get the absolute path to the directory where app.py is located
basedir = os.path.abspath(os.path.dirname(__file__))

# --- Configuration ---
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY') or os.urandom(24)
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///' + os.path.join(basedir, 'site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Profile picture uploads
UPLOAD_FOLDER = os.path.join(basedir, 'static/profile_pics')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True) # Create folder if it doesn't exist

# Email configuration (ensure these are set as environment variables for production)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER') or 'smtp.example.com'
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT') or 587)
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() in ['true', '1', 't']
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME') or 'your_email@example.com'
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD') or 'your_email_password'
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER') or 'your_email@example.com'


db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# --- Database Models ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    theme_preference = db.Column(db.String(20), default='dark')
    profile_image_file = db.Column(db.String(20), nullable=False, default='default.svg') # New field

    tasks = db.relationship('Task', backref='user', lazy=True, cascade='all, delete-orphan')
    categories = db.relationship('Category', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_task_stats(self):
        total = len(self.tasks)
        completed = sum(1 for task in self.tasks if task.completed)
        pending = total - completed
        overdue = sum(1 for task in self.tasks if task.due_date and task.due_date < date.today() and not task.completed)
        today_tasks = sum(1 for task in self.tasks if task.due_date == date.today())
        return {
            'total': total, 'completed': completed, 'pending': pending,
            'overdue': overdue, 'today': today_tasks,
            'completion_rate': round((completed / total * 100) if total > 0 else 0, 1)
        }

    @property
    def profile_pic_url(self):
        return url_for('static', filename=f'profile_pics/{self.profile_image_file}')


    def __repr__(self):
        return f"User('{self.email}')"

# ... (Category and Task models remain the same) ...
class Category(db.Model):
    """Category model for organizing tasks."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(7), default='#00bcd4')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tasks = db.relationship('Task', backref='category', lazy=True)

class Task(db.Model):
    """Enhanced Task model with additional fields."""
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    completed = db.Column(db.Boolean, default=False)
    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    priority = db.Column(db.String(10), default='medium')
    notes = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)

    @property
    def is_overdue(self):
        return self.due_date and self.due_date < date.today() and not self.completed
    @property
    def days_until_due(self):
        if not self.due_date: return None
        return (self.due_date - date.today()).days
    def __repr__(self):
        return f"Task('{self.description}', Completed: {self.completed}, Due: {self.due_date})"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# --- Helper for Profile Picture ---
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_picture(form_picture):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext
    picture_path = os.path.join(app.root_path, 'static/profile_pics', picture_fn)
    
    # # Optional: Resize image before saving to save space
    # from PIL import Image
    # output_size = (125, 125)
    # i = Image.open(form_picture)
    # i.thumbnail(output_size)
    # i.save(picture_path)
    
    form_picture.save(picture_path) # Save original for now
    return picture_fn

# ... (send_email, create_default_categories_for_new_user, auth routes, task routes, category routes remain the same) ...
# --- Routes ---

@app.before_request
def create_default_categories_for_new_user():
    if current_user.is_authenticated and not current_user.categories:
        try:
            default_categories = [
                Category(name='Work', color='#ff6b6b', user_id=current_user.id),
                Category(name='Personal', color='#4ecdc4', user_id=current_user.id),
                Category(name='Learning', color='#45b7d1', user_id=current_user.id),
                Category(name='Health', color='#96ceb4', user_id=current_user.id),
            ]
            db.session.bulk_save_objects(default_categories)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error creating default categories for user {current_user.id}: {e}")

@app.route('/')
def home():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email, name, password, confirm_password = request.form.get('email'), request.form.get('name', ''), request.form.get('password'), request.form.get('confirm_password')
        if not all([email, password, confirm_password]):
            flash('Please fill in all required fields.', 'error'); return render_template('register.html')
        if password != confirm_password:
            flash('Passwords do not match.', 'error'); return render_template('register.html')
        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'error'); return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please login or use a different email.', 'error'); return render_template('register.html')
        user = User(email=email, name=name); user.set_password(password)
        db.session.add(user); db.session.commit()
        flash('Account created successfully! You can now log in.', 'success'); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email, password = request.form.get('email'), request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user); flash('Logged in successfully!', 'success')
            return redirect(request.args.get('next') or url_for('dashboard'))
        else: flash('Login Unsuccessful. Please check email and password.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user(); flash('You have been logged out.', 'info'); return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    stats = current_user.get_task_stats()
    filter_status, filter_priority, filter_category, sort_by, search_query = \
        request.args.get('status', 'all'), request.args.get('priority', 'all'), \
        request.args.get('category', 'all'), request.args.get('sort', 'created_at_desc'), \
        request.args.get('search', '').strip()
    query = Task.query.filter_by(user_id=current_user.id)
    if filter_status == 'completed': query = query.filter_by(completed=True)
    elif filter_status == 'pending': query = query.filter_by(completed=False)
    elif filter_status == 'overdue': query = query.filter(Task.due_date < date.today(), Task.completed == False)
    if filter_priority != 'all': query = query.filter_by(priority=filter_priority)
    if filter_category != 'all':
        try: query = query.filter_by(category_id=int(filter_category))
        except ValueError: flash('Invalid category selected.', 'error'); filter_category = 'all'
    if search_query: query = query.filter((Task.description.ilike(f"%{search_query}%")) | (Task.notes.ilike(f"%{search_query}%")))
    if sort_by == 'due_date_asc': query = query.order_by(Task.due_date.asc(), Task.priority.desc())
    elif sort_by == 'due_date_desc': query = query.order_by(Task.due_date.desc(), Task.priority.desc())
    elif sort_by == 'priority': query = query.order_by(db.case((Task.priority == 'urgent', 1),(Task.priority == 'high', 2),(Task.priority == 'medium', 3),(Task.priority == 'low', 4),else_=5),Task.due_date.asc())
    elif sort_by == 'created_at_asc': query = query.order_by(Task.created_at.asc())
    else: query = query.order_by(Task.created_at.desc())
    tasks, categories = query.all(), Category.query.filter_by(user_id=current_user.id).all()
    return render_template('Dashboard.html', stats=stats, tasks=tasks, categories=categories,
                           current_filters={'status': filter_status, 'priority': filter_priority, 'category': filter_category, 'sort': sort_by, 'search': search_query})

@app.route('/tasks')
@login_required
def tasks_list(): return redirect(url_for('dashboard'))

@app.route('/add_task', methods=['POST'])
@login_required
def add_task():
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    desc, due_str, prio, cat_id, notes = request.form.get('task_description'), request.form.get('due_date'), request.form.get('priority', 'medium'), request.form.get('category_id'), request.form.get('notes', '')
    if desc:
        due = None
        if due_str:
            try: due = datetime.strptime(due_str, '%Y-%m-%d').date()
            except ValueError:
                msg = 'Invalid date format. Please use YYYY-MM-DD.'
                if is_ajax: return jsonify(success=False, message=msg), 400
                flash(msg, 'error'); return redirect(request.referrer or url_for('dashboard'))
        new_task = Task(description=desc, user_id=current_user.id, due_date=due, priority=prio, category_id=int(cat_id) if cat_id and cat_id.isdigit() else None, notes=notes)
        db.session.add(new_task); db.session.commit(); msg = 'Task added successfully!'
        if is_ajax: return jsonify(success=True, message=msg)
        flash(msg, 'success'); return redirect(request.referrer or url_for('dashboard'))
    else:
        msg = 'Task description cannot be empty.'
        if is_ajax: return jsonify(success=False, message=msg), 400
        flash(msg, 'error'); return redirect(request.referrer or url_for('dashboard'))

@app.route('/complete_task/<int:task_id>', methods=['POST'])
@login_required
def complete_task(task_id):
    task = db.session.get(Task, task_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if not task or task.user_id != current_user.id:
        msg = 'Task not found or you do not have permission to modify it.'
        if is_ajax: return jsonify(success=False, message=msg), 404
        flash(msg, 'error'); return redirect(request.referrer or url_for('dashboard'))
    try:
        task.completed = not task.completed
        task.completed_at = datetime.utcnow() if task.completed else None
        db.session.commit(); msg = 'Task status updated!'
        if is_ajax: return jsonify(success=True, message=msg)
        flash(msg, 'success'); return redirect(request.referrer or url_for('dashboard'))
    except Exception as e:
        db.session.rollback(); print(f"Error toggling task: {e}"); msg = 'Error updating task.'
        if is_ajax: return jsonify(success=False, message=f"Server error: {e}"), 500
        flash(msg, 'error'); return redirect(request.referrer or url_for('dashboard'))

@app.route('/delete_task/<int:task_id>', methods=['POST'])
@login_required
def delete_task(task_id):
    task = db.session.get(Task, task_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if not task or task.user_id != current_user.id:
        msg = 'Task not found or permission denied.'
        if is_ajax: return jsonify(success=False, message=msg), 404
        flash(msg, 'error'); return redirect(request.referrer or url_for('dashboard'))
    try:
        db.session.delete(task); db.session.commit(); msg = 'Task deleted successfully!'
        if is_ajax: return jsonify(success=True, message=msg)
        flash(msg, 'success'); return redirect(request.referrer or url_for('dashboard'))
    except Exception as e:
        db.session.rollback(); print(f"Error deleting task: {e}"); msg = 'Error deleting task.'
        if is_ajax: return jsonify(success=False, message=f"Server error: {e}"), 500
        flash(msg, 'error'); return redirect(request.referrer or url_for('dashboard'))

@app.route('/edit_task/<int:task_id>', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    task = db.session.get(Task, task_id)
    if not task or task.user_id != current_user.id:
        flash('Task not found or permission denied.', 'error'); return redirect(url_for('dashboard'))
    categories = Category.query.filter_by(user_id=current_user.id).all()
    if request.method == 'POST':
        task.description, task.priority, cat_id, task.notes = \
            request.form.get('task_description'), request.form.get('priority', 'medium'), \
            request.form.get('category_id'), request.form.get('notes', '')
        due_str = request.form.get('due_date')
        if due_str:
            try: task.due_date = datetime.strptime(due_str, '%Y-%m-%d').date()
            except ValueError: flash('Invalid date format.', 'error'); return render_template('edit_task.html', task=task, categories=categories)
        else: task.due_date = None
        task.category_id = int(cat_id) if cat_id and cat_id.isdigit() else None
        db.session.commit(); flash('Task updated successfully!', 'success'); return redirect(url_for('dashboard'))
    return render_template('edit_task.html', task=task, categories=categories)

@app.route('/calendar')
@login_required
def calendar_view():
    today = date.today(); return render_template('calendar.html', year=today.year, month=today.month)

@app.route('/api/tasks_by_date/<int:year>/<int:month>')
@login_required
def api_tasks_by_date(year, month):
    start_date, (_, num_days) = date(year, month, 1), calendar.monthrange(year, month)
    end_date = date(year, month, num_days)
    tasks_in_month = Task.query.filter(Task.user_id == current_user.id, Task.due_date >= start_date, Task.due_date <= end_date).order_by(Task.due_date).all()
    tasks_by_date = {}
    for task in tasks_in_month:
        if task.due_date:
            date_str = task.due_date.isoformat()
            if date_str not in tasks_by_date: tasks_by_date[date_str] = []
            tasks_by_date[date_str].append({
                'id': task.id, 'description': task.description, 'completed': task.completed,
                'priority': task.priority, 'category': task.category.name if task.category else None,
                'category_color': task.category.color if task.category else '#00bcd4',
                'is_overdue': task.is_overdue, 'notes': task.notes
            })
    return jsonify(tasks_by_date)

@app.route('/categories', methods=['GET', 'POST'])
@login_required
def manage_categories():
    if request.method == 'POST':
        name, color = request.form.get('name'), request.form.get('color', '#00bcd4')
        if name:
            if Category.query.filter_by(user_id=current_user.id, name=name).first():
                flash(f'Category "{name}" already exists.', 'error')
            else:
                db.session.add(Category(name=name, color=color, user_id=current_user.id)); db.session.commit()
                flash('Category added successfully!', 'success')
        else: flash('Category name cannot be empty.', 'error')
    categories = Category.query.filter_by(user_id=current_user.id).all()
    return render_template('categories.html', categories=categories)

@app.route('/delete_category/<int:category_id>', methods=['POST'])
@login_required
def delete_category(category_id):
    category = db.session.get(Category, category_id)
    if category and category.user_id == current_user.id:
        Task.query.filter_by(category_id=category_id, user_id=current_user.id).update({'category_id': None})
        db.session.delete(category); db.session.commit()
        flash('Category deleted. Associated tasks are now uncategorized.', 'success')
    else: flash('Category not found or permission denied.', 'error')
    return redirect(url_for('manage_categories'))


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        is_theme_update_ajax = 'theme_preference' in request.form and \
                               request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                               # Removed len and name check for simplicity, assuming JS sends only theme for AJAX theme update

        if is_theme_update_ajax:
            current_user.theme_preference = request.form.get('theme_preference', current_user.theme_preference)
            # If only theme is sent, we assume name is not being changed by this specific AJAX call.
            db.session.commit()
            return jsonify(success=True, message="Theme updated via AJAX.")

        # Full profile update from form submission (non-AJAX)
        current_user.name = request.form.get('name', current_user.name)
        current_user.theme_preference = request.form.get('theme_preference', current_user.theme_preference)
        
        # Profile picture upload
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename != '' and allowed_file(file.filename):
                # Delete old picture if it's not the default
                if current_user.profile_image_file != 'default.svg':
                    old_pic_path = os.path.join(app.root_path, 'static/profile_pics', current_user.profile_image_file)
                    if os.path.exists(old_pic_path):
                        try:
                            os.remove(old_pic_path)
                        except Exception as e:
                            print(f"Error deleting old profile picture: {e}")
                
                filename = save_picture(file)
                current_user.profile_image_file = filename
            elif file.filename != '': # File was selected but not allowed
                 flash('Invalid file type for profile picture. Allowed types: png, jpg, jpeg, gif.', 'error')


        new_password = request.form.get('new_password')
        current_password = request.form.get('current_password')
        password_changed = False

        if new_password: 
            if not current_password or not current_user.check_password(current_password):
                flash('Current password is incorrect.', 'error')
                # Ensure other changes are not lost if password change fails by re-rendering with current form data
                return render_template('profile.html', name=current_user.name, theme_preference=current_user.theme_preference)


            if len(new_password) < 6:
                flash('New password must be at least 6 characters long.', 'error')
                return render_template('profile.html', name=current_user.name, theme_preference=current_user.theme_preference)


            current_user.set_password(new_password)
            password_changed = True
        
        try:
            db.session.commit()
            if password_changed:
                flash('Profile and password updated successfully!', 'success')
            else:
                flash('Profile updated successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred: {e}', 'error')
            
        return redirect(url_for('profile'))

    return render_template('profile.html')


@app.route('/send_overdue_notifications')
@login_required
def send_overdue_notifications():
    overdue_tasks = Task.query.filter(Task.user_id == current_user.id, Task.due_date < date.today(),Task.completed == False).all()
    if not overdue_tasks:
        flash('No overdue tasks to send notifications for.', 'info'); return redirect(url_for('dashboard'))
    subject = 'Overdue Task Reminder from Your Task Tracker!'
    body_tasks = "\n".join([f"- {task.description} (Due: {task.due_date})" for task in overdue_tasks])
    body = f"Hello {current_user.name or current_user.email},\n\nYou have overdue tasks:\n\n{body_tasks}\n\nPlease complete them.\n\nBest,\nTask Tracker"
    if send_email(current_user.email, subject, body):
        flash(f'Email notification sent for {len(overdue_tasks)} overdue tasks.', 'success')
    else: flash('Failed to send email. Check server config.', 'error')
    return redirect(url_for('dashboard'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)