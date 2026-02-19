from werkzeug.security import generate_password_hash
from app import app, db
from models import User

def create_admin_user():
    """Create default admin user"""
    with app.app_context():
        # Check if admin already exists
        existing_admin = User.query.filter_by(username='admin').first()
        
        if existing_admin:
            print("Admin user already exists. Updating password...")
            existing_admin.set_password('admin123')
            db.session.commit()
            print("✅ Password updated!")
        else:
            # Create new admin user
            admin = User(
                username='admin',
                full_name='System Administrator',
                role='UtsavPramukh',
                is_active=True
            )
            admin.set_password('admin123')
            
            db.session.add(admin)
            db.session.commit()
            
            print("✅ Admin user created successfully!")
        
        print("=" * 50)
        print("Login Credentials:")
        print("  Username: admin")
        print("  Password: admin123")
        print("=" * 50)
        print("⚠️  CHANGE THIS PASSWORD AFTER FIRST LOGIN!")

if __name__ == '__main__':
    create_admin_user()